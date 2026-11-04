"""Append-only audit log of chat turns (JSON Lines): who asked what, which tools ran, which drafts were saved.

The log holds customer data (names, drafts), so it is created owner-read/write only (0600).
Path: AUDIT_LOG_PATH (default logs/audit.jsonl). Writing never raises: a broken log must not break the chat,
but every failure is logged loudly.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone

log = logging.getLogger('banking_crm.audit')
_lock = threading.Lock()


def audit_path() -> str:
    return os.getenv('AUDIT_LOG_PATH', 'logs/audit.jsonl')


def write_audit(event: str, **fields) -> None:
    record = {'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'), 'event': event, **fields}
    path = audit_path()
    try:
        line = json.dumps(record, ensure_ascii=False, default=str) + '\n'
        with _lock:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as fh:
                fh.write(line)
    except Exception:
        log.exception('AUDIT LOG WRITE FAILED (%s) for event %s', path, event)
