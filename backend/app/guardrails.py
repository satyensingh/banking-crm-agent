"""Deterministic guardrails: WhatsApp draft content rules, RM password auth, chat input limits.

Pure standard library, no LLM involved, so every rule is predictable and unit-tested.

Create a password hash for RM_USERS:   python -m app.guardrails hash-password
"""
import base64
import functools
import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque

# ---- WhatsApp draft content ------------------------------------------------------------------

DRAFT_MAX_CHARS = 600

# (code, human-readable reason sent back to the model, pattern)
_DRAFT_RULES = [
    ('PROMISE_OF_APPROVAL', 'must not promise or imply approval (e.g. "guaranteed", "pre-approved", "approved")',
     re.compile(r'\b(guarantee[ds]?|pre-?approved|approved|approval\s+assured|assured|instant\s+approval|'
                r'risk[- ]free|100\s*%\s*(sure|approval)|sure[- ]shot)\b', re.I)),
    ('RATE_OR_AMOUNT', 'must not state interest rates, loan amounts or EMI figures',
     re.compile(r'\d+(\.\d+)?\s*(%|percent\b|p\.?a\.?\b)|(₹|\brs\.?|\binr\b)\s*\d|'
                r'\b\d[\d,.]*\s*(lakh|lakhs|lac|lacs|crore|crores|k)\b|\bemi\s+of\b', re.I)),
    ('CONTACT_OR_LINK', 'must not contain links, email addresses or phone numbers',
     re.compile(r'https?://|\bwww\.|\b[\w.+-]+@[\w-]+\.[\w.]+\b|\+?\d[\d\s-]{8,}\d')),
]


def check_draft(content: str) -> list[str]:
    """Return the list of violated rules (empty = acceptable). Each item is 'CODE: reason'."""
    problems = [f'{code}: {reason}' for code, reason, pattern in _DRAFT_RULES if pattern.search(content)]
    if len(content) > DRAFT_MAX_CHARS:
        problems.append(f'TOO_LONG: must be at most {DRAFT_MAX_CHARS} characters (got {len(content)})')
    return problems


# ---- RM password auth ------------------------------------------------------------------------
# Hash format (no '$' so it is safe in .env / docker compose): pbkdf2_sha256:<iterations>:<salt>:<hash>
# RM_USERS format: user1=<hash>,user2=<hash>

_ALGO, _ITERATIONS = 'pbkdf2_sha256', 600_000


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    return f'{_ALGO}:{iterations}:{_b64(salt)}:{_b64(digest)}'


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split(':')
        if algo != _ALGO:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), _unb64(salt), int(iterations))
        return hmac.compare_digest(actual, _unb64(digest))
    except (ValueError, TypeError):
        return False


def load_users(raw: str | None = None) -> dict[str, str]:
    """Parse RM_USERS ('alice=<hash>,bob=<hash>'). Malformed entries are skipped."""
    raw = os.getenv('RM_USERS', '') if raw is None else raw
    users = {}
    for entry in raw.split(','):
        name, sep, stored = entry.strip().partition('=')
        if sep and name.strip() and stored.strip().startswith(f'{_ALGO}:'):
            users[name.strip()] = stored.strip()
    return users


@functools.cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_hex(16))


def authenticate(username: str, password: str, users: dict[str, str] | None = None) -> bool:
    users = load_users() if users is None else users
    stored = users.get(username)
    # Always run one hash so unknown users take as long as known ones (no username probing by timing).
    ok = verify_password(password, stored or _dummy_hash())
    return bool(stored) and ok


DEV_SECRET_PREFIX = 'dev-insecure-'
DEMO_USER, DEMO_PASSWORD = 'rm', 'rm-demo-password'  # the documented .env.example login


def dev_default_warnings(users: dict[str, str] | None = None) -> list[str]:
    """Warnings for the dev-only defaults from .env.example, so they are never silently used for real."""
    users = load_users() if users is None else users
    warnings = []
    if os.getenv('CHAINLIT_AUTH_SECRET', '').startswith(DEV_SECRET_PREFIX):
        warnings.append('CHAINLIT_AUTH_SECRET is the dev default from .env.example - replace it '
                        '(chainlit create-secret) before anyone else can reach this app')
    if DEMO_USER in users and verify_password(DEMO_PASSWORD, users[DEMO_USER]):
        warnings.append(f"RM_USERS contains the demo login '{DEMO_USER}' / '{DEMO_PASSWORD}' - replace it "
                        '(python -m app.guardrails hash-password) before anyone else can reach this app')
    return warnings


# ---- Chat input limits -----------------------------------------------------------------------

def max_message_chars() -> int:
    return int(os.getenv('CHAT_MAX_MESSAGE_CHARS', '4000'))


class RateLimiter:
    """Sliding-window limit of `limit` messages per `window` seconds, per key (the RM)."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, hits = self.clock(), self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> int:
        hits = self._hits.get(key)
        return max(1, int(self.window - (self.clock() - hits[0])) + 1) if hits else 0


if __name__ == '__main__':
    import getpass
    import sys
    if sys.argv[1:] != ['hash-password']:
        sys.exit('usage: python -m app.guardrails hash-password')
    first = getpass.getpass('Password: ')
    if len(first) < 12:
        sys.exit('Use at least 12 characters.')
    if getpass.getpass('Repeat: ') != first:
        sys.exit('Passwords do not match.')
    print(hash_password(first))
