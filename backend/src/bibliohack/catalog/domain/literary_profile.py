"""Literary profile — audience + literary-form classification of a record.

biblioHack targets adult readers of **literature** — novels and every genre
of fiction (sci-fi, crime, fantasy, …) plus poetry and drama. It is *not* a
catalogue of children's picture books, school textbooks, or reference works.
This module decides, per record, whether it belongs to that target so the
catalogue and recommender can scope to it **by default**.

Design rule: **classify, don't discard.** The media-type filter
(`media_filter.py`) already drops non-books (magazines, CDs, DVDs…) at
ingest, because media type is a stable, high-confidence MARC-leader signal
and genuinely out of scope. Audience and fiction/non-fiction are *not* media
types — the signals are fuzzier (YA that adults read, literary non-fiction)
and the boundary is one we may want to retune. So every accepted book is
still ingested; this profile is stored alongside it and used only to scope
reads. A query can always widen the scope, and re-running the classifier
re-derives everything without a re-crawl.

Two orthogonal axes, each with an explicit ``UNKNOWN`` so we never silently
guess — and ``UNKNOWN`` stays *inside* the default scope, so an
under-catalogued novel is shown rather than hidden:

    Audience      — ADULT / YOUTH / CHILDREN
    LiteraryForm  — LITERARY (belles-lettres) / NONFICTION

Signals, strongest first:

1.  **Copy signature (tejuelo)** — the strongest *real-world* signal, because
    librarians physically shelve by it (RBPA convention, validated against
    the titn_1 fixture)::

        N…           adult narrative        → ADULT   + LITERARY
        P… / T…      poetry / theatre       → ADULT   + LITERARY
        I… / I-N…    infantil               → CHILDREN (+ LITERARY if narrative)
        J… / J-N…    juvenil                → YOUTH    (+ LITERARY if narrative)
        3-B-522 / UNI 6383 …  topographic / deposit code → no signal

    A record can hold copies in several sections (a poem shelved in both the
    adult *and* the children's room). We let **ADULT evidence win**, because
    the question the default scope answers is "can an adult reader get this?".

2.  **CDU / UDC classification (T080)** — record-level::

        starts 82… or 860…   literature (belles-lettres)  → LITERARY
        contains .09          literary criticism/history   → NONFICTION
        any other class       0-7, 9, 80/81 linguistics…   → NONFICTION
        contains -93 or 087.5 infantil/juvenil             → CHILDREN

3.  *(future)* MARC 008/22 target-audience byte — not parsed yet.
4.  Subjects (T650) inform genre facets, not the keep/hide decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class Audience(StrEnum):
    """Who a work is shelved for. ``UNKNOWN`` is inside the default scope."""

    ADULT = "adult"
    YOUTH = "youth"
    CHILDREN = "children"
    UNKNOWN = "unknown"


class LiteraryForm(StrEnum):
    """Belles-lettres vs. non-fiction. ``UNKNOWN`` is inside the default scope."""

    LITERARY = "literary"  # novels, sci-fi & all genres, poetry, drama, comics
    NONFICTION = "nonfiction"
    UNKNOWN = "unknown"


class Genre(StrEnum):
    """Coarse literary genre, derived from CDU form divisions + tejuelos.

    MARC subject headings (T650/655) are too sparse in this catalogue to
    carry a genre facet, so we derive one from the signals we *do* have:
    the CDU form division after a literature class (``821.134.2-1`` → ``-1``
    poetry) and the copy signature section letters (``N``/``P``/``T``).
    Same philosophy as the rest of this module: classify, don't discard;
    ``UNKNOWN`` is an honest first-class value, re-derivable without a
    re-crawl.
    """

    NARRATIVE = "narrative"  # novela y toda la ficción narrativa
    POETRY = "poetry"
    DRAMA = "drama"  # teatro
    ESSAY = "essay"  # ensayo literario (CDU -4)
    COMIC = "comic"  # CDU 741.5
    UNKNOWN = "unknown"


class SearchScope(StrEnum):
    """Which slice of the catalogue a read should cover.

    ``LITERARY`` is the default biblioHack experience (adult literature, all
    genres); ``ALL`` lifts the filter so children's books, non-fiction, etc.
    are searchable when explicitly asked for.
    """

    LITERARY = "literary"
    ALL = "all"


# Audiences shown by the default ("literary") scope — adult plus the
# can't-tell case, so we never hide a novel we simply failed to classify.
_DEFAULT_AUDIENCES: frozenset[Audience] = frozenset({Audience.ADULT, Audience.UNKNOWN})
_DEFAULT_FORMS: frozenset[LiteraryForm] = frozenset({LiteraryForm.LITERARY, LiteraryForm.UNKNOWN})


@dataclass(frozen=True, slots=True)
class LiteraryProfile:
    """How a record scores on the audience and literary-form axes."""

    audience: Audience = Audience.UNKNOWN
    form: LiteraryForm = LiteraryForm.UNKNOWN

    @property
    def in_default_scope(self) -> bool:
        """True if this record appears in the default catalogue/recommender view.

        Adult-or-unknown audience AND literary-or-unknown form — i.e. we hide
        only records we are *confident* are for children/youth or are
        non-fiction.
        """
        return self.audience in _DEFAULT_AUDIENCES and self.form in _DEFAULT_FORMS


def default_scope_audiences() -> tuple[str, ...]:
    """Audience values inside the default scope, for a persistence-layer filter."""
    return tuple(a.value for a in _DEFAULT_AUDIENCES)


def default_scope_forms() -> tuple[str, ...]:
    """Literary-form values inside the default scope, for a persistence filter."""
    return tuple(f.value for f in _DEFAULT_FORMS)


def classify_literary_profile(
    *,
    classification: str | None,
    signatures: Iterable[str | None] = (),
) -> LiteraryProfile:
    """Derive a :class:`LiteraryProfile` from a record's CDU + its copy signatures.

    ``classification`` is the UDC/T080 string (e.g. ``'821.134.2-1"19"'``).
    ``signatures`` are the per-copy tejuelos (e.g. ``"N ARS roh"``). Both are
    optional and noisy; the resolution rules below tolerate missing/garbage
    input and fall back to ``UNKNOWN`` rather than guessing.
    """
    audiences: set[Audience] = set()
    forms: set[LiteraryForm] = set()

    for signature in signatures:
        audience, form = _from_signature(signature)
        if audience is not None:
            audiences.add(audience)
        if form is not None:
            forms.add(form)

    audience, form = _from_cdu(classification)
    if audience is not None:
        audiences.add(audience)
    if form is not None:
        forms.add(form)

    return LiteraryProfile(audience=_resolve_audience(audiences), form=_resolve_form(forms))


def derive_genre(
    *,
    classification: str | None,
    signatures: Iterable[str | None] = (),
) -> Genre:
    """Coarse genre from the CDU form division, falling back to tejuelos.

    The CDU wins when it speaks — it's the cataloguer's explicit intent
    (``821.134.2-3…`` is narrative whatever room a copy sits in). Signatures
    only break the tie when the CDU is silent, with NARRATIVE preferred on
    conflict (the overwhelmingly common case). Comics are recognised by the
    CDU ``741.5`` class, which sits outside the 82… literature range.
    """
    from_cdu = _genre_from_cdu(classification)
    if from_cdu is not Genre.UNKNOWN:
        return from_cdu

    signals: set[Genre] = set()
    for signature in signatures:
        genre = _genre_from_signature(signature)
        if genre is not Genre.UNKNOWN:
            signals.add(genre)
    for candidate in (Genre.NARRATIVE, Genre.POETRY, Genre.DRAMA, Genre.COMIC):
        if candidate in signals:
            return candidate
    return Genre.UNKNOWN


# CDU form division right after a literature class: '821.134.2-31"19"' → '3'.
# Accepts both modern 82… and legacy 86… (860 Spanish-literature) classes.
_CDU_GENRE_RE = re.compile(r"^8[26][\d.]*-(\d)")


def _genre_from_cdu(classification: str | None) -> Genre:
    if not classification:
        return Genre.UNKNOWN
    code = classification.strip()
    if code.startswith("741.5"):
        return Genre.COMIC
    match = _CDU_GENRE_RE.match(code)
    if match is None:
        return Genre.UNKNOWN
    return {
        "1": Genre.POETRY,
        "2": Genre.DRAMA,
        "3": Genre.NARRATIVE,
        "4": Genre.ESSAY,
    }.get(match.group(1), Genre.UNKNOWN)


def _genre_from_signature(signature: str | None) -> Genre:
    if not signature:
        return Genre.UNKNOWN
    match = _SIG_TOKEN_RE.match(signature.strip())
    if match is None:
        return Genre.UNKNOWN
    parts = match.group(1).upper().split("-")
    head = parts[0]
    if head == "N" or "N" in parts[1:]:  # adult narrativa, or an I-N / J-N arm
        return Genre.NARRATIVE
    if head == "P":
        return Genre.POETRY
    if head == "T":
        return Genre.DRAMA
    if head == "C":  # cómic section (RBPA); single letter only — "CO…" stays out
        return Genre.COMIC if len(parts) == 1 and len(head) == 1 else Genre.UNKNOWN
    return Genre.UNKNOWN


# ───────────────────────────────────────────────────────────────
# Resolution — combine the (possibly conflicting) signals
# ───────────────────────────────────────────────────────────────


def _resolve_audience(signals: set[Audience]) -> Audience:
    """ADULT wins (it's gettable by adults), then YOUTH, then CHILDREN."""
    for candidate in (Audience.ADULT, Audience.YOUTH, Audience.CHILDREN):
        if candidate in signals:
            return candidate
    return Audience.UNKNOWN


def _resolve_form(signals: set[LiteraryForm]) -> LiteraryForm:
    """LITERARY wins over NONFICTION, so a borderline title stays visible."""
    if LiteraryForm.LITERARY in signals:
        return LiteraryForm.LITERARY
    if LiteraryForm.NONFICTION in signals:
        return LiteraryForm.NONFICTION
    return LiteraryForm.UNKNOWN


# ───────────────────────────────────────────────────────────────
# Signature (tejuelo) signal
# ───────────────────────────────────────────────────────────────

# Leading section token: one or more letters, optionally hyphenated
# ("J-N"), anchored at the start and followed by a word boundary. A tejuelo
# that starts with a digit ("3-B-522") is a topographic/deposit code and
# matches nothing here — deliberately, it carries no audience/form signal.
_SIG_TOKEN_RE = re.compile(r"^([A-Za-zÁÉÍÓÚÜÑ]+(?:-[A-Za-zÁÉÍÓÚÜÑ]+)?)\b")


def _from_signature(signature: str | None) -> tuple[Audience | None, LiteraryForm | None]:
    if not signature:
        return (None, None)
    match = _SIG_TOKEN_RE.match(signature.strip())
    if match is None:
        return (None, None)
    token = match.group(1).upper()
    parts = token.split("-")
    head = parts[0]
    is_narrative = "N" in parts  # an "-N" arm (or a bare "N") ⇒ narrative

    if head == "I":  # infantil
        return (Audience.CHILDREN, LiteraryForm.LITERARY if is_narrative else None)
    if head == "J":  # juvenil
        return (Audience.YOUTH, LiteraryForm.LITERARY if is_narrative else None)
    if head == "N":  # narrativa (adult)
        return (Audience.ADULT, LiteraryForm.LITERARY)
    if head in ("P", "T"):  # poesía / teatro (adult)
        return (Audience.ADULT, LiteraryForm.LITERARY)
    return (None, None)  # R (referencia), UNI, CO… — uninformative for now


# ───────────────────────────────────────────────────────────────
# CDU / UDC signal
# ───────────────────────────────────────────────────────────────

# Leading numeric class of a UDC string — stops at the first non-[digit.]
# char, so '821.134.2-1"19"' → '821.134.2'.
_CDU_CLASS_RE = re.compile(r"^(\d[\d.]*)")


def _from_cdu(classification: str | None) -> tuple[Audience | None, LiteraryForm | None]:
    if not classification:
        return (None, None)
    code = classification.strip()

    # Infantil/juvenil markers can appear anywhere in the code.
    audience = Audience.CHILDREN if ("-93" in code or "087.5" in code) else None

    match = _CDU_CLASS_RE.match(code)
    if match is None:
        return (audience, None)
    numeric = match.group(1)

    # ".09" is the form division for criticism / history of literature, i.e.
    # a non-fiction work *about* literature — not a literary work itself.
    if ".09" in code:
        return (audience, LiteraryForm.NONFICTION)
    # 82… (modern) and 860… (legacy Spanish-literature) are belles-lettres.
    # 80/81/811 are linguistics — non-fiction — so we require the "82" prefix.
    if numeric.startswith(("82", "860")):
        return (audience, LiteraryForm.LITERARY)
    return (audience, LiteraryForm.NONFICTION)
