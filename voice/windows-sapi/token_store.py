# SPDX-License-Identifier: MIT
"""One atomic local token, usable before starting the adapter. No COM/server side effects."""
import os
from pathlib import Path
import re
import secrets
import uuid


def ensure_token(path=None):
    """Return a 43-character URL-safe token, creating once without overwriting.

    The token is private configuration; callers must never expose it in a catalog,
    preference response, log, URL, command argument, or public source copy.
    """
    target = Path(path) if path is not None else Path(__file__).resolve().parent / "api-token.txt"
    if not target.exists():
        temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="ascii") as output:
                output.write(secrets.token_urlsafe(32))
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, target)  # Atomic create-if-absent; never replaces another caller's token.
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    token = target.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError("INVALID_SAPI_TOKEN_FILE")
    return token
