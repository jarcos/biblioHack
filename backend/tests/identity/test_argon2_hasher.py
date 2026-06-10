"""Argon2PasswordHasher tests — real argon2, minimal cost parameters."""

from __future__ import annotations

import pytest

from bibliohack.identity.infrastructure.security.argon2_hasher import Argon2PasswordHasher


@pytest.fixture(scope="module")
def hasher() -> Argon2PasswordHasher:
    # Cheapest sane parameters — these tests prove behaviour, not strength.
    return Argon2PasswordHasher(time_cost=1, memory_cost_kib=8 * 1024, parallelism=1)


def test_round_trip(hasher: Argon2PasswordHasher) -> None:
    encoded = hasher.hash("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert hasher.verify("correct horse battery staple", encoded)


def test_wrong_password_fails(hasher: Argon2PasswordHasher) -> None:
    encoded = hasher.hash("correct horse battery staple")
    assert not hasher.verify("incorrect horse", encoded)


def test_malformed_hash_fails_instead_of_raising(hasher: Argon2PasswordHasher) -> None:
    assert not hasher.verify("anything", "not-an-argon2-hash")


def test_salts_differ_between_hashes(hasher: Argon2PasswordHasher) -> None:
    assert hasher.hash("same password") != hasher.hash("same password")


def test_needs_rehash_when_parameters_strengthen(hasher: Argon2PasswordHasher) -> None:
    encoded = hasher.hash("password-ten")
    assert not hasher.needs_rehash(encoded)
    stronger = Argon2PasswordHasher(time_cost=2, memory_cost_kib=8 * 1024, parallelism=1)
    assert stronger.needs_rehash(encoded)
    assert stronger.needs_rehash("garbage")
