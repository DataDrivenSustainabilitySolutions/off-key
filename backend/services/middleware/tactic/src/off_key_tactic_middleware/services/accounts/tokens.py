"""Store only digests of the single-use and session tokens TACTIC issues."""

import hashlib


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
