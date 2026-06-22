"""Postgres reads/writes for branches (Libraries milestone).

Geocode work-queue methods for the L0 enrich sweep. Kept set-based and small;
the geo enrich use case drives the pacing/retry logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, update

from bibliohack.holdings.infrastructure.postgres.models import (
    BranchModel,
    UserFollowedBranchModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class BranchGeoRow:
    """Minimal branch shape for the geocode sweep (matches UngeocodedBranch)."""

    code: str
    municipality: str | None
    province: str | None


@dataclass(frozen=True, slots=True)
class BranchSummary:
    """Public branch shape for the API (drives the client-side proximity sort)."""

    code: str
    name: str
    municipality: str | None
    province: str | None
    lat: float | None
    lng: float | None


class PostgresBranchRepository:
    """Branch reads/writes for the Libraries milestone."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def iter_ungeocoded(self, *, limit: int, offset: int = 0) -> Sequence[BranchGeoRow]:
        """Active branches with a municipality but no coordinates yet."""
        stmt = (
            select(BranchModel.code, BranchModel.municipality, BranchModel.province)
            .where(
                BranchModel.is_active.is_(True),
                BranchModel.municipality.isnot(None),
                BranchModel.lat.is_(None),
            )
            .order_by(BranchModel.code.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            BranchGeoRow(code=r.code, municipality=r.municipality, province=r.province)
            for r in rows
        ]

    async def set_geo(self, code: str, *, lat: float, lng: float) -> None:
        """Persist resolved coordinates for one branch."""
        await self._session.execute(
            update(BranchModel).where(BranchModel.code == code).values(lat=lat, lng=lng)
        )

    # --- public list + per-user follows (L1) ---------------------------------

    async def list_active(self) -> Sequence[BranchSummary]:
        """All active branches, name-ordered — the browser distance-sorts these."""
        stmt = (
            select(
                BranchModel.code,
                BranchModel.name,
                BranchModel.municipality,
                BranchModel.province,
                BranchModel.lat,
                BranchModel.lng,
            )
            .where(BranchModel.is_active.is_(True))
            .order_by(BranchModel.name.asc(), BranchModel.code.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            BranchSummary(
                code=r.code,
                name=r.name,
                municipality=r.municipality,
                province=r.province,
                lat=r.lat,
                lng=r.lng,
            )
            for r in rows
        ]

    async def followed_codes(self, user_id: str) -> list[str]:
        """Branch codes the user follows, in saved display order."""
        stmt = (
            select(UserFollowedBranchModel.branch_code)
            .where(UserFollowedBranchModel.user_id == user_id)
            .order_by(
                UserFollowedBranchModel.position.asc().nulls_last(),
                UserFollowedBranchModel.branch_code.asc(),
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def scope_branch_codes(self, user_id: str, level: str) -> list[str] | None:
        """Branch codes for a library scope level (Libraries L3).

        - ``"mine"``     → the user's followed branches.
        - ``"province"`` → every active branch in a province the user follows.
        - ``"full"`` (or no follows) → ``None`` (the whole catalogue).

        Returns ``None`` (not ``[]``) when there's nothing to scope to, so the
        caller treats it as full catalogue rather than "match nothing".
        """
        if level == "mine":
            return (await self.followed_codes(user_id)) or None
        if level == "province":
            followed_provinces = (
                select(BranchModel.province)
                .join(
                    UserFollowedBranchModel,
                    UserFollowedBranchModel.branch_code == BranchModel.code,
                )
                .where(
                    UserFollowedBranchModel.user_id == user_id,
                    BranchModel.province.isnot(None),
                )
            )
            stmt = select(BranchModel.code).where(
                BranchModel.is_active.is_(True),
                BranchModel.province.in_(followed_provinces),
            )
            return list((await self._session.execute(stmt)).scalars().all()) or None
        return None

    async def existing_codes(self, codes: Sequence[str]) -> set[str]:
        """Subset of `codes` that are real, active branch codes (input validation)."""
        if not codes:
            return set()
        stmt = select(BranchModel.code).where(
            BranchModel.code.in_(list(codes)), BranchModel.is_active.is_(True)
        )
        return set((await self._session.execute(stmt)).scalars().all())

    async def set_followed(self, user_id: str, codes: Sequence[str]) -> None:
        """Replace the user's follow set with `codes` (order preserved as position)."""
        await self._session.execute(
            delete(UserFollowedBranchModel).where(UserFollowedBranchModel.user_id == user_id)
        )
        seen: set[str] = set()
        rows: list[dict[str, object]] = []
        for position, code in enumerate(codes):
            if code in seen:  # dedupe, keep first occurrence's position
                continue
            seen.add(code)
            rows.append({"user_id": user_id, "branch_code": code, "position": position})
        if rows:
            # Core bulk insert (not ORM add) — avoids the insertmanyvalues
            # sentinel path that trips on a client-supplied composite PK.
            await self._session.execute(insert(UserFollowedBranchModel), rows)
