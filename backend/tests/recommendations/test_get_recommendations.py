"""GetRecommendations use-case tests (in-memory fakes)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.recommendations.application.ports import (
    Candidate,
    CandidateBatch,
    ColdStartProfile,
)
from bibliohack.recommendations.application.use_cases.get_recommendations import (
    GetRecommendations,
    RecommendationsError,
)
from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeShelf:
    def __init__(self, fingerprint: str | None, *, raw_shelf: tuple[str, ...] = ()) -> None:
        self._fingerprint = fingerprint
        self._raw_shelf = raw_shelf

    async def fingerprint(self, user_id: str) -> str | None:
        return self._fingerprint

    async def raw_shelf(self, user_id: str) -> tuple[str, ...]:
        return self._raw_shelf


class FakeRetriever:
    def __init__(
        self, batch: CandidateBatch, *, cold_start_batch: CandidateBatch | None = None
    ) -> None:
        self._batch = batch
        self._cold_start_batch = cold_start_batch or CandidateBatch(liked_books=(), candidates=())
        self.calls = 0
        self.cold_start_calls = 0
        self.last_kwargs: dict[str, object] = {}

    async def retrieve(
        self,
        user_id: str,
        *,
        limit: int,
        followed_branch_codes: list[str] | None = None,
        nearby_only: bool = False,
    ) -> CandidateBatch:
        self.calls += 1
        self.last_kwargs = {
            "followed_branch_codes": followed_branch_codes,
            "nearby_only": nearby_only,
        }
        return self._batch

    async def retrieve_cold_start(self, descriptor: str, *, limit: int) -> CandidateBatch:
        self.cold_start_calls += 1
        return self._cold_start_batch


class FakeClassifier:
    def __init__(self, profile: ColdStartProfile | None = None) -> None:
        self._profile = profile
        self.calls = 0

    async def infer(self, shelf_titles: Sequence[str]) -> ColdStartProfile | None:
        self.calls += 1
        return self._profile


class FakeRationales:
    def __init__(self, rationales: dict[str, str] | None = None) -> None:
        self._rationales = rationales or {}

    async def write(
        self, *, liked_books: Sequence[str], candidates: Sequence[Candidate]
    ) -> dict[str, str]:
        return self._rationales


class FakeRepository:
    def __init__(self, cached: tuple[Recommendation, ...] | None = None) -> None:
        self._cached = cached
        self.replaced: tuple[str, tuple[Recommendation, ...]] | None = None

    async def get_cached(self, user_id: str, cache_key: str) -> tuple[Recommendation, ...] | None:
        return self._cached

    async def replace(
        self, user_id: str, cache_key: str, recommendations: Sequence[Recommendation]
    ) -> None:
        self.replaced = (cache_key, tuple(recommendations))


def _batch() -> CandidateBatch:
    return CandidateBatch(
        liked_books=("Cien años de soledad — García Márquez",),
        candidates=(
            Candidate(record_id="rec-1", title="Nada", author="Carmen Laforet", score=0.91),
            Candidate(record_id="rec-2", title="La colmena", author="Cela", score=0.88),
        ),
    )


async def test_empty_profile_short_circuits() -> None:
    """No matched books AND an empty raw shelf → EMPTY_PROFILE, nothing retrieved."""
    retriever = FakeRetriever(_batch())
    classifier = FakeClassifier(ColdStartProfile(descriptor="x"))
    result = await GetRecommendations(
        shelf=FakeShelf(None),  # empty raw_shelf by default
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(),
        classifier=classifier,
        limit=10,
    ).execute("u-1")
    assert result == Err(RecommendationsError.EMPTY_PROFILE)
    assert retriever.calls == 0
    assert classifier.calls == 0  # empty shelf short-circuits before the LLM


async def test_cache_hit_skips_retrieval() -> None:
    cached = (Recommendation(record_id="rec-9", score=0.8, rationale="ya generada"),)
    retriever = FakeRetriever(_batch())
    result = await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(cached=cached),
        classifier=FakeClassifier(),
        limit=10,
    ).execute("u-1")
    assert isinstance(result, Ok)
    assert result.value.recommendations == cached
    assert result.value.cold_start is False
    assert retriever.calls == 0


async def test_cache_miss_generates_decorates_and_persists() -> None:
    repository = FakeRepository()
    result = await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=FakeRetriever(_batch()),
        rationales=FakeRationales({"rec-1": "Posguerra íntima, como lo que sueles puntuar alto."}),
        repository=repository,
        classifier=FakeClassifier(),
        limit=10,
    ).execute("u-1")

    assert isinstance(result, Ok)
    first, second = result.value.recommendations
    assert first.rationale == "Posguerra íntima, como lo que sueles puntuar alto."
    assert second.rationale is None  # the LLM only covered rec-1
    assert repository.replaced is not None
    assert repository.replaced[0] == "fp-1"
    assert repository.replaced[1] == result.value.recommendations


async def test_empty_retrieval_is_cached_ok() -> None:
    repository = FakeRepository()
    result = await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=FakeRetriever(CandidateBatch(liked_books=(), candidates=())),
        rationales=FakeRationales(),
        repository=repository,
        classifier=FakeClassifier(),
        limit=10,
    ).execute("u-1")
    assert isinstance(result, Ok)
    assert result.value.recommendations == ()
    assert repository.replaced == ("fp-1", ())


async def test_library_context_threads_to_retriever() -> None:
    retriever = FakeRetriever(_batch())
    await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(),
        classifier=FakeClassifier(),
        limit=10,
    ).execute("u-1", library_codes=["AL03", "AL04"], nearby_only=True)
    assert retriever.last_kwargs == {
        "followed_branch_codes": ["AL03", "AL04"],
        "nearby_only": True,
    }


async def test_library_context_changes_the_cache_key() -> None:
    """No follows → plain fingerprint; follows / nearby → distinct keys."""

    async def key_for(library_codes: list[str] | None, *, nearby: bool) -> str:
        repo = FakeRepository()
        await GetRecommendations(
            shelf=FakeShelf("fp-1"),
            retriever=FakeRetriever(_batch()),
            rationales=FakeRationales(),
            repository=repo,
            classifier=FakeClassifier(),
            limit=10,
        ).execute("u-1", library_codes=library_codes, nearby_only=nearby)
        assert repo.replaced is not None
        return repo.replaced[0]

    plain = await key_for(None, nearby=False)
    mine = await key_for(["AL03"], nearby=False)
    nearby_only = await key_for(["AL03"], nearby=True)

    assert plain == "fp-1"  # no library context → unchanged (back-compat)
    assert mine != plain
    assert nearby_only != mine  # toggling nearby regenerates


# ── cold-start (§8.3.3) ─────────────────────────────────────────


def _cold_batch() -> CandidateBatch:
    return CandidateBatch(
        liked_books=(),
        candidates=(Candidate(record_id="rec-7", title="Patria", author="Aramburu", score=0.74),),
    )


async def test_cold_start_infers_and_retrieves_when_nothing_matched() -> None:
    """fingerprint None but a non-empty raw shelf → LLM infers taste → KNN."""
    repository = FakeRepository()
    retriever = FakeRetriever(_batch(), cold_start_batch=_cold_batch())
    classifier = FakeClassifier(
        ColdStartProfile(descriptor="novela histórica española", tastes=("novela histórica",))
    )
    result = await GetRecommendations(
        shelf=FakeShelf(None, raw_shelf=("Patria — Aramburu", "Los pilares de la tierra")),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=repository,
        classifier=classifier,
        limit=10,
    ).execute("u-1")

    assert isinstance(result, Ok)
    assert result.value.cold_start is True
    assert result.value.inferred_tastes == ("novela histórica",)
    assert [r.record_id for r in result.value.recommendations] == ["rec-7"]
    assert retriever.cold_start_calls == 1
    assert retriever.calls == 0  # never used the taste-centroid path
    assert repository.replaced is not None


async def test_cold_start_falls_back_to_empty_profile_when_llm_down() -> None:
    """A non-empty shelf but the classifier returns None → today's behaviour."""
    retriever = FakeRetriever(_batch(), cold_start_batch=_cold_batch())
    result = await GetRecommendations(
        shelf=FakeShelf(None, raw_shelf=("Algún libro",)),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(),
        classifier=FakeClassifier(None),  # LLM unavailable
        limit=10,
    ).execute("u-1")

    assert result == Err(RecommendationsError.EMPTY_PROFILE)
    assert retriever.cold_start_calls == 0


async def test_cold_start_cache_key_busts_when_shelf_changes() -> None:
    """The cold-start cache key is derived from the raw titles, so a changed
    shelf regenerates."""

    async def key_for(raw_shelf: tuple[str, ...]) -> str:
        repo = FakeRepository()
        await GetRecommendations(
            shelf=FakeShelf(None, raw_shelf=raw_shelf),
            retriever=FakeRetriever(_batch(), cold_start_batch=_cold_batch()),
            rationales=FakeRationales(),
            repository=repo,
            classifier=FakeClassifier(ColdStartProfile(descriptor="d")),
            limit=10,
        ).execute("u-1")
        assert repo.replaced is not None
        return repo.replaced[0]

    one = await key_for(("Patria — Aramburu",))
    two = await key_for(("Patria — Aramburu", "Otra novela"))
    assert one != two
