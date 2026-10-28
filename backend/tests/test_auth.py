import base64
import json
import os
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.auth import _admin_emails, decode_session_token, require_admin


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def make_session_token(claims: dict, secret: str, salt: str = "") -> str:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        info=(
            f"NextAuth.js Generated Encryption Key ({salt})"
            if salt
            else "NextAuth.js Generated Encryption Key"
        ).encode(),
    ).derive(secret.encode())

    header_b64 = _b64(json.dumps({"alg": "dir", "enc": "A256GCM"}).encode())
    iv = os.urandom(12)
    iv_b64 = _b64(iv)
    encrypted = AESGCM(key).encrypt(iv, json.dumps(claims).encode(), header_b64.encode())
    ciphertext, tag = encrypted[:-16], encrypted[-16:]
    return f"{header_b64}..{iv_b64}.{_b64(ciphertext)}.{_b64(tag)}"


def test_decode_session_token_roundtrip():
    secret = "test-secret"
    token = make_session_token(
        {"email": "admin@zaddp.io", "role": "admin", "exp": int(time.time()) + 60},
        secret,
    )

    claims = decode_session_token(token, secret=secret)

    assert claims["email"] == "admin@zaddp.io"
    assert claims["role"] == "admin"


def test_decode_session_token_rejects_expired():
    secret = "test-secret"
    token = make_session_token({"email": "viewer@zaddp.io", "exp": 1}, secret)

    with pytest.raises(ValueError, match="expired"):
        decode_session_token(token, secret=secret)


def test_decode_session_token_requires_secret(monkeypatch):
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)

    with pytest.raises(RuntimeError):
        decode_session_token("a.b.c.d.e")


def test_require_admin_allows_role_and_allowlist(monkeypatch):
    monkeypatch.setenv("ML_ADMIN_EMAILS", "secops@bank.com")

    assert require_admin({"role": "admin"})["role"] == "admin"
    assert require_admin({"email": "SECOPS@bank.com"})["email"] == "SECOPS@bank.com"


def test_require_admin_rejects_viewer(monkeypatch):
    monkeypatch.setenv("ML_ADMIN_EMAILS", "secops@bank.com")

    with pytest.raises(Exception) as exc:
        require_admin({"email": "viewer@bank.com", "role": "viewer"})

    assert getattr(exc.value, "status_code", None) == 403
    assert _admin_emails() == {"secops@bank.com"}
