"""GetRecommendations use-case tests (in-memory fakes)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.recommendations.application.ports import Candidate, CandidateBatch
from bibliohack.recommendations.application.use_cases.get_recommendations import (
    GetRecommendations,
    RecommendationsError,
)
from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeShelf:
    def __init__(self, fingerprint: str | None) -> None:
        self._fingerprint = fingerprint

    async def fingerprint(self, user_id: str) -> str | None:
        return self._fingerprint


class FakeRetriever:
    def __init__(self, batch: CandidateBatch) -> None:
        self._batch = batch
        self.calls = 0
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
    retriever = FakeRetriever(_batch())
    result = await GetRecommendations(
        shelf=FakeShelf(None),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(),
        limit=10,
    ).execute("u-1")
    assert result == Err(RecommendationsError.EMPTY_PROFILE)
    assert retriever.calls == 0


async def test_cache_hit_skips_retrieval() -> None:
    cached = (Recommendation(record_id="rec-9", score=0.8, rationale="ya generada"),)
    retriever = FakeRetriever(_batch())
    result = await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(cached=cached),
        limit=10,
    ).execute("u-1")
    assert result == Ok(cached)
    assert retriever.calls == 0


async def test_cache_miss_generates_decorates_and_persists() -> None:
    repository = FakeRepository()
    result = await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=FakeRetriever(_batch()),
        rationales=FakeRationales({"rec-1": "Posguerra íntima, como lo que sueles puntuar alto."}),
        repository=repository,
        limit=10,
    ).execute("u-1")

    assert isinstance(result, Ok)
    first, second = result.value
    assert first.rationale == "Posguerra íntima, como lo que sueles puntuar alto."
    assert second.rationale is None  # the LLM only covered rec-1
    assert repository.replaced is not None
    assert repository.replaced[0] == "fp-1"
    assert repository.replaced[1] == result.value


async def test_empty_retrieval_is_cached_ok() -> None:
    repository = FakeRepository()
    result = await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=FakeRetriever(CandidateBatch(liked_books=(), candidates=())),
        rationales=FakeRationales(),
        repository=repository,
        limit=10,
    ).execute("u-1")
    assert result == Ok(())
    assert repository.replaced == ("fp-1", ())


async def test_library_context_threads_to_retriever() -> None:
    retriever = FakeRetriever(_batch())
    await GetRecommendations(
        shelf=FakeShelf("fp-1"),
        retriever=retriever,
        rationales=FakeRationales(),
        repository=FakeRepository(),
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
