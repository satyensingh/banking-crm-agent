"""Deterministic guardrails: draft content rules, password auth, rate limiting, audit log."""
import json
import os
import stat

import pytest

from app import audit
from app.guardrails import (DRAFT_MAX_CHARS, RateLimiter, authenticate, check_draft, hash_password,
                            load_users, verify_password)

GOOD = ('Hi Asha, hope you are well. Based on your relationship with us, a personal loan could suit '
        'your plans. Reply here or speak with your RM to know more.')


def codes(text): return {p.split(':')[0] for p in check_draft(text)}


def test_compliant_draft_passes():
    assert check_draft(GOOD) == []


@pytest.mark.parametrize('text', [
    'Your loan is guaranteed!', 'You are pre-approved for a loan', 'You are preapproved', 'Loan approved for you',
    'Approval assured', 'Instant approval today', 'A risk-free offer'])
def test_promises_of_approval_are_rejected(text):
    assert 'PROMISE_OF_APPROVAL' in codes(text)


@pytest.mark.parametrize('text', [
    'Rates from 10.5% only', 'just 11 percent', 'Get ₹5,00,000 today', 'Rs. 50000 available', 'INR 200000',
    'up to 5 lakh', 'up to 2 crore', 'up to 500k', 'an EMI of just a little'])
def test_rates_amounts_and_emi_are_rejected(text):
    assert 'RATE_OR_AMOUNT' in codes(text)


@pytest.mark.parametrize('text', [
    'Apply at https://bank.example/apply', 'see www.bank.example', 'mail me at rm@bank.example',
    'Call +91 98765 43210', 'call 9876543210'])
def test_links_and_contact_details_are_rejected(text):
    assert 'CONTACT_OR_LINK' in codes(text)


@pytest.mark.parametrize('text', [
    'We noticed your recent spending on travel', 'I saw your tuition payment', 'Your recent transactions show',
    'Since you spent on home repairs', 'Your salary has gone up', 'We have observed your purchases'])
def test_revealing_transaction_monitoring_is_rejected(text):
    assert 'TRANSACTION_REFERENCE' in codes(text)


@pytest.mark.parametrize('text', ['Help with medical bills', 'After your hospitalisation', 'For your health needs'])
def test_health_topics_are_rejected(text):
    assert 'SENSITIVE_TOPIC' in codes(text)


def test_personalised_theme_draft_passes():
    draft = ('Hi Asha, thank you for 7 years with us in Pune. If you have education plans coming up, a '
             'Personal Loan - Premium could help. We would love to see how we can support you: reply here '
             'or speak with your RM.')
    assert check_draft(draft) == []


def test_length_limit():
    assert codes('a' * DRAFT_MAX_CHARS) == set()
    assert codes('a' * (DRAFT_MAX_CHARS + 1)) == {'TOO_LONG'}


def test_ordinary_words_and_numbers_are_not_flagged():
    # 'approval' as a process (not a promise) and plain small numbers are fine
    assert check_draft('Any loan is subject to approval. We have served you for 5 years.') == []


def test_password_hash_roundtrip_and_format():
    stored = hash_password('correct horse battery', iterations=1000)
    assert stored.startswith('pbkdf2_sha256:1000:') and '$' not in stored  # safe in .env / compose
    assert verify_password('correct horse battery', stored)
    assert not verify_password('wrong', stored)
    assert hash_password('same', iterations=1000) != hash_password('same', iterations=1000)  # salted
    assert not verify_password('x', 'garbage') and not verify_password('x', 'md5:1:a:b')


def test_load_users_and_authenticate():
    h1, h2 = hash_password('pw-one-123456', iterations=1000), hash_password('pw-two-123456', iterations=1000)
    users = load_users(f' alice={h1} , bob={h2}, broken, eve=plaintext, ={h1}')
    assert set(users) == {'alice', 'bob'}
    assert authenticate('alice', 'pw-one-123456', users)
    assert not authenticate('alice', 'pw-two-123456', users)
    assert not authenticate('mallory', 'pw-one-123456', users)
    assert not authenticate('alice', 'pw-one-123456', {})
    assert load_users('') == {}


def test_rate_limiter_sliding_window():
    now = [0.0]
    rl = RateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert rl.allow('a') and rl.allow('a') and not rl.allow('a')
    assert rl.allow('b')  # per-user
    assert 1 <= rl.retry_after('a') <= 61
    now[0] = 60.0
    assert rl.allow('a')


def test_audit_log_appends_json_lines_owner_only(tmp_path, monkeypatch):
    path = tmp_path / 'sub' / 'audit.jsonl'
    monkeypatch.setenv('AUDIT_LOG_PATH', str(path))
    audit.write_audit('turn', user='alice', prompt='top prospects', drafts=[{'customer_id': 42}])
    audit.write_audit('login', user='bob', ok=False)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['event'] for r in rows] == ['turn', 'login']
    assert rows[0]['user'] == 'alice' and rows[0]['drafts'] == [{'customer_id': 42}] and 'ts' in rows[0]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_audit_failure_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    monkeypatch.setenv('AUDIT_LOG_PATH', str(blocker / 'audit.jsonl'))  # parent is a file -> cannot write
    audit.write_audit('turn', user='alice')  # must not raise


def _env_example() -> dict[str, str]:
    from pathlib import Path
    values = {}
    for line in (Path(__file__).resolve().parents[2] / '.env.example').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.startswith('#'):
            values[key.strip()] = value.strip()
    return values


def test_env_example_defaults_work_out_of_the_box():
    from app.guardrails import DEMO_PASSWORD, DEMO_USER, DEV_SECRET_PREFIX
    env = _env_example()
    assert env['CHAINLIT_AUTH_SECRET'].startswith(DEV_SECRET_PREFIX) and len(env['CHAINLIT_AUTH_SECRET']) >= 32
    assert '$' not in env['CHAINLIT_AUTH_SECRET'] + env['RM_USERS']  # compose would interpolate '$'
    users = load_users(env['RM_USERS'])
    assert authenticate(DEMO_USER, DEMO_PASSWORD, users)  # the documented login really signs in
    assert not authenticate(DEMO_USER, 'wrong', users)


def test_dev_defaults_raise_startup_warnings(monkeypatch):
    from app.guardrails import DEMO_PASSWORD, DEMO_USER, dev_default_warnings
    env = _env_example()
    monkeypatch.setenv('CHAINLIT_AUTH_SECRET', env['CHAINLIT_AUTH_SECRET'])
    warnings = dev_default_warnings(load_users(env['RM_USERS']))
    assert len(warnings) == 2 and all('replace it' in w for w in warnings)
    monkeypatch.setenv('CHAINLIT_AUTH_SECRET', 'a-real-secret-from-create-secret')
    real = load_users(f"rm={hash_password('a-different-password', iterations=1000)}")
    assert dev_default_warnings(real) == []
    assert DEMO_USER == 'rm' and DEMO_PASSWORD == 'rm-demo-password'
