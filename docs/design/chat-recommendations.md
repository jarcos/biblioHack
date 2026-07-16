---
title: "biblioHack — Chat & Recommendations"
h1: "Chat & Recommendations — feedback loops and a catalogue-grounded chatbot"
tagline: "Designed 2026-07-03 · proposal — P1 queued behind reskin phase 2 (M8 stays the mobile app)."
---
The recommender today (`/recommendations`, M5 + §8.3.3 cold-start) is a
one-way street: per-user pgvector KNN over a **taste centroid** built from the
shelf, decorated with best-effort LLM rationales, cached under a shelf
fingerprint. The reader can't talk back — no way to say *"more like this"*,
*"never again"*, or *"I read it, it was wonderful"* — and no way to explore
("something Andalusian and melancholic, under 300 pages") without editing
their shelf and hoping.

This milestone adds the conversation: **feedback signals** on every
recommendation, a **read-after-recommended** rating loop, a **chatbot** that
discusses the reader's shelf and tastes and can only ever recommend from the
catalogue, and a persistent **taste profile** that all three write into and
the retrieval engine reads from.

> **Status: P1 shipped 2026-07-16; P2–P4 proposal.** Design agreed 2026-07-03
> in conversation; grounded in the shipped recommender (`recommendations/`
> context, §8.3.3 cold-start, library-aware boost from
> [`library-aware-availability.md`](library-aware-availability.html)).
> Phases 1–4 below ship independently; 1, 2 and 4 carry Alembic revisions.
> **P1** (feedback buttons, `recommendation_feedback`, weighted centroid,
> cache-key busting) is live — the reader's like/dislike now re-weights
> retrieval and regenerates the batch. UI lands on the **reskin phase-2**
> recommendations page, not the old one.

---

## 1. What exists, and what's missing

`GetRecommendations` (the use case) already does the hard parts:

- **Per-user, end to end.** Shelf → fingerprint → cached batch under
  `user_id`; cold-start infers taste from raw imported titles via OpenRouter
  and embeds the descriptor. Everything downstream keys on `user_id`. Nothing
  needs multi-tenanting; it already is.
- **Semantic similarity, not metadata matching.** Candidates rank by cosine
  distance to the centroid in BGE-M3 space (1024-d, via the HF Inference
  API). This is why "Murakami readers may like Dostoevsky" works without any
  author/country/subject rule: closeness lives in the embedding, not in
  MARC fields.
- **Catalogue-bounded by construction.** The retriever *is* a query over
  `bibliographic_records`; it cannot return a book we don't hold.
- **Cache that busts itself.** `cache_key` = shelf fingerprint (+ library
  context). Shelf moves → key changes → batch regenerates.

What's missing is every **return channel**: the batch is write-only (old
batches are `replace()`d away, so we can't even tell "you read this because
we suggested it"), the centroid hears only the shelf, and there is no
conversational surface at all.

## 2. Resolved design decisions

Each decision was pressure-tested on 2026-07-03; later rows depend on
earlier ones.

| # | Question | Decision |
| --- | --- | --- |
| D1 | Fine-tune a model on the catalogue? | **No.** "Mastery in literature" comes from the base model; "knows the catalogue" comes from retrieval. The catalogue **grows** (M7 sweep ongoing), so a fine-tune is a stale snapshot by design. Chatbot = tool-calling LLM + `search_catalog` over the existing pgvector index. |
| D2 | Host a local model on the NAS? | **No (for now).** The NAS is RAM-constrained and already runs Postgres/Redis/API/crawler — same reasoning that put BGE-M3 on the HF Inference API instead of the box. Chat goes through the existing **OpenRouter** integration (`OPENROUTER_MODEL`, per-message cost in cents). Revisit only with dedicated hardware; candidates then: Qwen3-4B-class GGUF via llama.cpp (best small-model Spanish as of mid-2026). |
| D3 | How is "catalogue-only" enforced? | **Retrieve-then-pick.** The model never names books in free text: it calls `search_catalog`, receives candidate `record_id`s, and may only recommend those ids. The UI renders book cards from ids, never from prose. (Validate-after — fuzzy-matching model output against the catalogue — is rejected: it launders hallucinations through near-miss matches.) |
| D4 | What does a like/dislike actually do? | Writes a row to `recommendation_feedback`; the centroid becomes a **weighted mean** (§4) and the feedback state joins the cache key, so the next request regenerates. Not decoration. |
| D5 | How do we know a recommended book was read? | The shelf already records reads. **Impressions** (append-only batch snapshots, §3) make the join possible: shelf entry marked read × prior impression → prompt for a rating at mark-read time. |
| D6 | Raw chat history into the recommender? | **Never.** After a chat session, one LLM call distils/updates a per-user **taste profile** (structured text + its embedding). The recommender blends the profile embedding into the centroid; transcripts are kept only for chat continuity. The profile is the real data model — chat, buttons and read-ratings are just its writers. |
| D7 | Catalogue growth vs. cached batches | Cache key gains a coarse **catalogue epoch** (embedded-record count, bucketed weekly). New arrivals → epoch ticks → stale batches regenerate against the bigger catalogue automatically. |
| D8 | Where does the UI live? | Reskin **phase-2** recommendations page. New endpoints under **`/api/*`** (dashboard-managed tunnel routes nothing else). Chat streams over SSE. |

## 3. Data model (three tables, all per-user)

**`recommendation_feedback`** — the signal store. One row per
(user, record, signal) event; latest signal per record wins.

| column | type | notes |
| --- | --- | --- |
| `id` | uuid pk | |
| `user_id` | uuid fk users, cascade | |
| `record_id` | uuid fk bibliographic_records, cascade | |
| `signal` | enum | `like` · `dislike` · `more_like_this` · `not_interested` · `read_rating` |
| `rating` | smallint null | 1–5, only for `read_rating` |
| `created_at` | timestamptz | |

**`recommendation_impressions`** — append-only history of what was actually
shown (today `replace()` destroys it). Written whenever a batch is generated;
never updated. Columns: `user_id`, `record_id`, `cache_key`, `shown_at`.
This is what makes D5's join — and any future quality metric ("how many
impressions convert to reads?") — possible.

**`taste_profiles`** — one row per user: `profile_text` (structured: likes,
dislikes, moods, constraints), `profile_embedding vector(1024)`,
`updated_at`, `source` (`chat` · `import` · `manual`). Rewritten by the
distiller (D6), read by the retriever (§4).

Chat transcripts live in a fourth, boring table (`chat_messages`:
`user_id`, `role`, `content`, `created_at`) that **nothing but the chat UI
reads**. Alembic revisions: phase 1 (feedback), phase 2 (impressions),
phase 4 (profiles + chat).

## 4. Scoring: the weighted centroid

Today: centroid = mean of shelf-book embeddings. It becomes a weighted mean
over every signal source:

| source | weight | notes |
| --- | --- | --- |
| shelf books (read/owned) | **+1.0** | unchanged baseline |
| `read_rating` 4–5 | **+1.2** | a loved recommendation is the strongest signal we have |
| `like` / `more_like_this` | **+0.7** | |
| taste-profile embedding | **+0.8** | one vector, from chat (D6) |
| `read_rating` 1–2 | **−0.6** | |
| `dislike` | **−0.5** | plus **hard exclusion** of the record itself |
| `not_interested` | 0 | hard exclusion only — "not now" ≠ "not my taste" |

Negative weights *push* the centroid away from disliked regions — this is
what makes "show me less like this" mean something. Weights are constants in
the retriever, not settings; tune them by looking at impressions→reads, not
by intuition.

**Cache identity** becomes
`hash(shelf fingerprint | library context | feedback-state hash | profile updated_at | catalogue epoch)`.
Any button press, chat session or weekly catalogue tick regenerates on the
next visit — this is D4 + D7's "re-runs automatically", with zero schedulers.

## 5. The chatbot («La Bibliotecaria»)

A tool-calling loop over the existing OpenRouter client — the §8.3.3
Andalusian-librarian persona, promoted from a one-shot classifier to a
conversation. System prompt: Spanish, literary, warm; **must** call tools to
mention any book; asked for recommendations, may only present ids returned
by `search_catalog`.

Tools (all read the user's existing contexts):

- `search_catalog(query, k)` — embed the query (HF API, same as cold-start
  descriptor), KNN over records with the literary-scope filter; returns
  `record_id`, title, author, availability summary.
- `read_shelf()` — the user's shelf with read/rating state.
- `get_current_recommendations()` — the live batch, so the chat can discuss
  *why* something was suggested (rationales are already stored).
- `save_preference(note)` — appends to a session scratchpad the distiller
  reads when the session closes.

Endpoint `POST /api/chat` (SSE stream), session-cookie auth like everything
else. Failure contract mirrors the recommender's: OpenRouter down → chat
politely unavailable; **recommendations never depend on the chat being up.**

Cost note: chat is the only per-message spend in the system. `:free`-tier
routing is fine for development; budget a paid model for real use before
promoting the feature out of the account menu.

## 6. The read-after-recommended loop

1. Batch generated → impressions written (§3).
2. Reader marks a book read on their shelf (existing flow).
3. Shelf write checks impressions: was this record ever shown to this user?
4. If yes → the mark-read UI asks one question («¿Qué te pareció?», 1–5,
   skippable) → `read_rating` row → feedback hash changes → next batch
   learns from it (±1.2/−0.6, §4).

No self-report guessing, no tracking beyond what the shelf already knows.

## 7. Phasing

| phase | ships | why first/here | migration |
| --- | --- | --- | --- |
| **P1 ✅ shipped 2026-07-16** | feedback buttons + `recommendation_feedback` + weighted centroid + cache-key busting | no LLM cost, immediate quality gain, foundation for everything | ✔ `20260716_0023` |
| **P2** | `recommendation_impressions` + mark-read rating prompt | closes the read loop; needs P1's table | ✔ |
| **P3** | chatbot MVP (tools: `search_catalog`, `read_shelf`, `get_current_recommendations`) on the reskin-phase-2 page | user-visible payoff; no recommender coupling yet | — |
| **P4** | `taste_profiles` + session distiller + centroid blend + catalogue epoch | the full loop: conversation changes what the engine retrieves | ✔ |

Each phase is a normal ship: gates green → push to `main` → CI deploys.
P1 alone already answers the original feature request's "like/dislike that
actually does something".

## 8. Open questions

- **Feedback decay** — should a two-year-old dislike weigh like yesterday's?
  (Proposal: no decay in P1; revisit with impressions data.)
- **Distiller trigger** — on session close vs. nightly batch. Session close
  is simpler and the volume (single-digit users) makes cost irrelevant.
- **Profile transparency** — the taste profile should eventually be visible
  and editable on the account page («esto creemos que te gusta») rather than
  a black box; UX belongs to the reskin phase-2 conversation.
- **Model choice for chat** — pick after P3 prototyping; the OpenRouter
  abstraction makes it a config change (`OPENROUTER_MODEL`).
