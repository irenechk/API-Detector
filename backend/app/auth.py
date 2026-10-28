"""NextAuth.js session verification for FastAPI.

NextAuth v4 stores the session as a JWE (A256GCM, direct key agreement).
The encryption key is derived from NEXTAUTH_SECRET with HKDF-SHA256 using
the session-cookie name as the salt.
"""

import base64
import json
import logging
import os
import time
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)

COOKIE_NAMES = (
    "__Secure-next-auth.session-token",
    "next-auth.session-token",
)

HKDF_INFO_PREFIX = "NextAuth.js Generated Encryption Key"


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive_key(secret: str, salt: str) -> bytes:
    info = f"{HKDF_INFO_PREFIX} ({salt})" if salt else HKDF_INFO_PREFIX
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        info=info.encode(),
    ).derive(secret.encode())


def _decrypt_jwe(token: str, secret: str, salt: str) -> dict:
    parts = token.split(".")
    if len(parts) != 5:
        raise ValueError("Malformed NextAuth JWE")

    header_b64, encrypted_key_b64, iv_b64, ciphertext_b64, tag_b64 = parts
    if encrypted_key_b64:
        raise ValueError("Unsupported NextAuth JWE key mode")

    header = json.loads(_b64url_decode(header_b64))
    if header.get("alg") != "dir" or header.get("enc") != "A256GCM":
        raise ValueError("Unsupported NextAuth JWE algorithm")

    ciphertext = _b64url_decode(ciphertext_b64) + _b64url_decode(tag_b64)
    if len(ciphertext) < 16:
        raise ValueError("Malformed NextAuth JWE ciphertext")

    # NextAuth v4 does not set a JWE "aad" member, so jose uses only the
    # protected header as additional authenticated data.
    plaintext = AESGCM(_derive_key(secret, salt)).decrypt(
        _b64url_decode(iv_b64),
        ciphertext,
        header_b64.encode(),
    )
    return json.loads(plaintext)


def decode_session_token(token: str, secret: Optional[str] = None) -> dict:
    """Decrypt a NextAuth session JWE and validate its expiry."""
    secret = secret or os.getenv("NEXTAUTH_SECRET")
    if not secret:
        raise RuntimeError("NEXTAUTH_SECRET is not configured")

    last_error: Optional[Exception] = None
    # NextAuth v4's default encoder derives the key with an empty salt. Also
    # try the cookie names to support deployments that configure a custom salt.
    for salt in ("", *COOKIE_NAMES):
        try:
            claims = _decrypt_jwe(token, secret, salt)
            break
        except Exception as exc:
            last_error = exc
    else:
        raise ValueError("Unable to decrypt NextAuth session token") from last_error

    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        raise ValueError("NextAuth session token has expired")

    return claims


def _session_cookie(request: Request) -> Optional[str]:
    for name in COOKIE_NAMES:
        value = request.cookies.get(name)
        if value:
            return value
    return None


def get_current_user(request: Request) -> dict:
    """Return the decoded NextAuth session claims, or raise 401."""
    token = _session_cookie(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return decode_session_token(token)
    except RuntimeError as exc:
        logger.error("Auth misconfiguration: %s", exc)
        raise HTTPException(status_code=500, detail="Authentication is not configured")
    except Exception as exc:
        logger.info("Rejected session token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid session")


def _admin_emails() -> set[str]:
    raw = os.getenv("ML_ADMIN_EMAILS", "admin@zaddp.io")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Allow admin-role sessions or emails listed in ML_ADMIN_EMAILS."""
    email = str(user.get("email", "")).lower()
    role = str(user.get("role", "")).lower()
    if role == "admin" or email in _admin_emails():
        return user
    raise HTTPException(status_code=403, detail="Admin role required")
