"""Keys and locked fields for the shared database.

A friend's journal is encrypted with a data key that the server never stores
in the clear. Copies of that key exist only wrapped: once under their
password, once under their recovery code, and once under each sign-in token
Claude holds for them. The server keeps fingerprints of those secrets, never
the secrets themselves -- so the database file, or any backup of it, cannot be
read without something only the friend or their Claude has.

What this does not do: the key is in memory while a signed-in call is being
served, so whoever runs the server could change the code to capture it. It
protects against reading the file, not against a dishonest operator.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"

# No 0/O, 1/I/L: these codes are read off a screen and typed by hand.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_data_key() -> bytes:
    return Fernet.generate_key()


def new_code(groups: int = 4) -> str:
    """A code a person can copy by hand, 4 characters to a group."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4))
                    for _ in range(groups))


def normalise_code(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def new_token() -> str:
    return secrets.token_urlsafe(32)


def fingerprint(secret: str) -> str:
    """What is stored in place of a high-entropy secret, to look it up by."""
    return hashlib.sha256(b"jyotisha-lookup:" + secret.encode()).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def _stretch(secret: str, salt: bytes) -> bytes:
    # For secrets a person chose or typed. Slow on purpose.
    return hashlib.scrypt(secret.encode(), salt=salt, n=2 ** 15, r=8, p=1,
                          dklen=32, maxmem=128 * 1024 * 1024)


def wrap_with_secret(key: bytes, secret: str) -> str:
    salt = os.urandom(16)
    box = Fernet(base64.urlsafe_b64encode(_stretch(secret, salt)))
    return _b64(salt) + "." + box.encrypt(key).decode()


def unwrap_with_secret(blob: str | None, secret: str) -> bytes | None:
    """The data key, or None when the secret is wrong."""
    try:
        salt, token = (blob or "").split(".", 1)
        box = Fernet(base64.urlsafe_b64encode(
            _stretch(secret, base64.urlsafe_b64decode(salt))))
        return box.decrypt(token.encode())
    except (ValueError, InvalidToken):
        return None


def _token_box(token: str) -> Fernet:
    # Tokens are 256 random bits, so one hash is enough -- and it is a
    # different hash from fingerprint(), so the stored fingerprint cannot
    # open what the token wraps.
    return Fernet(base64.urlsafe_b64encode(
        hashlib.sha256(b"jyotisha-wrap:" + token.encode()).digest()))


def wrap_with_token(key: bytes, token: str) -> str:
    return _token_box(token).encrypt(key).decode()


def unwrap_with_token(blob: str | None, token: str) -> bytes | None:
    try:
        return _token_box(token).decrypt((blob or "").encode())
    except (ValueError, InvalidToken):
        return None


class Cipher:
    """Locks and opens single field values under one account's data key."""

    def __init__(self, key: bytes):
        self._box = Fernet(key)

    def lock(self, value):
        if value is None:
            return None
        return PREFIX + self._box.encrypt(str(value).encode()).decode()

    def open(self, value):
        if not isinstance(value, str) or not value.startswith(PREFIX):
            return value
        return self._box.decrypt(value[len(PREFIX):].encode()).decode()
