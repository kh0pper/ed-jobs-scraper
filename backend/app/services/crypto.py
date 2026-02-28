"""Symmetric encryption for sensitive fields (tokens, credentials).

Uses Fernet encryption derived from the application's secret_key.
"""

import base64
import logging

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import get_settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Get or create Fernet instance from app secret_key."""
    global _fernet
    if _fernet is not None:
        return _fernet

    settings = get_settings()

    if settings.secret_key == "change-me-in-production":
        logger.warning(
            "Using default secret_key for encryption. "
            "Set SECRET_KEY env var for production use."
        )

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"edjobs-fernet-v1",
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode()))
    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning base64-encoded ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt base64-encoded ciphertext back to plaintext."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()
