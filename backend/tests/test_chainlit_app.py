"""Chainlit UI helpers (pure data shaping; the Chainlit runtime itself is not started)."""
import pytest

pytest.importorskip('chainlit')
pytest.importorskip('pandas')

from chainlit_app import STARTERS, prospects_frame


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
