"""Password hashing and verification.

Plain-text passwords are never stored. Each user row holds a one-way hash
built with PBKDF2-HMAC-SHA256, 120,000 iterations, and a per-user random
salt, written in the same format the seed database already uses::

    pbkdf2_sha256$<salt>$<hex digest>

A hash cannot be reversed to recover the password. To check a login we
re-hash what the user typed using the *stored* salt and the same iteration
count, then compare the result to the stored digest with a constant-time
comparison. Sign-up and login both go through :func:`hash_password`, so the
settings can never drift apart.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 120_000
SALT_BYTES = 8  # 8 random bytes -> 16 hex characters, matching the seed data


def hash_password(password: str, salt: str | None = None) -> str:
    """Return ``pbkdf2_sha256$salt$hexdigest`` for ``password``.

    A fresh random salt is generated unless one is supplied. Supplying the
    salt is only for verification, where we must reuse the stored one.
    """
    if salt is None:
        salt = secrets.token_hex(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        ITERATIONS,
    )
    return f"{ALGORITHM}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check ``password`` against a stored hash without ever decoding it.

    Steps: read the salt out of the stored string, re-hash the typed password
    with that salt, and compare the two full strings in constant time so the
    comparison's duration does not leak how many characters matched.
    """
    try:
        algorithm, salt, _digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate.encode("utf-8"), stored_hash.encode("utf-8"))


# When a login names an email that does not exist, we still run one hash
# against this dummy value so the request takes about as long as a real
# check. Otherwise an attacker could tell registered emails from unknown
# ones by timing the response.
DUMMY_HASH = hash_password("not-a-real-password")
