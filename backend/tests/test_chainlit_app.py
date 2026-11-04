"""Chainlit UI helpers (pure data shaping; the Chainlit runtime itself is not started)."""
import pytest

pytest.importorskip('chainlit')
pytest.importorskip('pandas')

import json

from app.guardrails import hash_password
from chainlit_app import STARTERS, auth_callback, prospects_frame


def test_prospects_frame_shapes_ui_customers_for_the_table():
    df = prospects_frame([
        {'id': 42, 'name': 'Asha Rao', 'city': 'Pune', 'score': 91, 'income': 130000.0, 'creditScore': 815,
         'balance': 240000.0, 'product': 'Pl Premium', 'reason': 'Strong profile', 'consent': True},
        {'id': 7, 'name': 'Ravi K', 'city': 'Delhi', 'score': 55, 'income': 50000.0, 'creditScore': 700,
         'balance': 1000.0, 'product': 'Pl Basic', 'reason': 'Ok', 'consent': False}])
    assert list(df['Customer']) == ['Asha Rao', 'Ravi K'] and list(df['Score']) == [91, 55]
    assert list(df['WhatsApp permitted']) == ['Yes', 'No']
    assert 'Monthly income (INR)' in df.columns and df.to_csv(index=False).startswith('Customer,ID,City')


def test_starters_are_label_message_pairs():
    assert len(STARTERS) == 4 and all(label and message for label, message in STARTERS)


async def test_login_accepts_known_rm_rejects_others_and_audits(tmp_path, monkeypatch):
    log_path = tmp_path / 'audit.jsonl'
    monkeypatch.setenv('AUDIT_LOG_PATH', str(log_path))
    monkeypatch.setenv('RM_USERS', f"asha={hash_password('a-long-password', iterations=1000)}")
    user = await auth_callback(' asha ', 'a-long-password')
    assert user is not None and user.identifier == 'asha' and user.metadata['role'] == 'rm'
    assert await auth_callback('asha', 'wrong-password') is None
    assert await auth_callback('nobody', 'a-long-password') is None
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [(e['event'], e['user'], e['ok']) for e in events] == [
        ('login', 'asha', True), ('login', 'asha', False), ('login', 'nobody', False)]
    assert all('password' not in json.dumps(e) for e in events)  # passwords are never logged
