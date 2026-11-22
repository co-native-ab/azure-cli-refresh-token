import base64
import json

import pytest

from azext_refresh_token import proof

START = 1_800_000_000


def make_token(**claims):
    def segment(value):
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return '.'.join([segment({'alg': 'HS256', 'typ': 'JWT'}), segment(claims), 'c2lnbmF0dXJl'])


def facts(token):
    return proof.inspect(token)


def test_fingerprint_is_twelve_hex_characters_of_the_sha256_hash():
    assert proof.fingerprint('abc') == 'ba7816bf8f01'


def test_inspect_reads_the_payload():
    token = make_token(iat=START, aud='https://arm.example.test/', tid='tenant', exp=START + 10)
    result = facts(token)
    assert (result.iat, result.aud, result.tid, result.exp) == \
        (START, 'https://arm.example.test/', 'tenant', START + 10)
    assert result.claims['aud'] == 'https://arm.example.test/'
    assert result.fingerprint == proof.fingerprint(token)


def test_audience_list_yields_the_first_entry():
    assert facts(make_token(iat=START, aud=['first', 'second'])).aud == 'first'


def test_facts_hold_no_header_or_signature():
    assert set(proof.TokenFacts._fields) == {'fingerprint', 'iat', 'aud', 'tid', 'exp', 'claims'}


@pytest.mark.parametrize('token', [
    'opaque-token-without-dots',
    'only.two',
    'a.b.c.d',
    'aaa.bm90LWpzb24.sig',
])
def test_tokens_that_are_not_readable_have_no_issue_time(token):
    assert facts(token).iat is None


def test_string_or_boolean_issue_time_is_unreadable():
    assert facts(make_token(iat='1800000000')).iat is None
    assert facts(make_token(iat=True)).iat is None
    assert facts(make_token(aud='x')).iat is None


def test_payload_that_is_not_an_object_is_unreadable():
    payload = base64.urlsafe_b64encode(b'[1, 2]').decode().rstrip('=')
    assert facts('h.' + payload + '.s').iat is None


def old():
    return facts(make_token(iat=START - 3600, jti='old'))


def test_backdated_new_token_is_proven():
    new = facts(make_token(iat=START - 300, jti='new'))
    assert proof.prove(old(), new, START) == 'proven'


def test_allowance_boundary():
    on_boundary = facts(make_token(iat=START - 600, jti='edge'))
    past_boundary = facts(make_token(iat=START - 601, jti='late'))
    assert proof.prove(old(), on_boundary, START) == 'proven'
    assert proof.prove(old(), past_boundary, START) == 'stale'


def test_same_token_wins_over_stale():
    token = make_token(iat=START - 3600, jti='old')
    assert proof.prove(facts(token), facts(token), START) == 'same'


def test_unreadable_start_or_final_token_cannot_be_proven():
    readable = facts(make_token(iat=START, jti='x'))
    unreadable = facts('opaque')
    assert proof.prove(unreadable, readable, START) == 'unreadable'
    assert proof.prove(readable, unreadable, START) == 'unreadable'


def test_label_edges():
    assert proof.label(facts(make_token(iat=START - 600)), START) == 'issued'
    assert proof.label(facts(make_token(iat=START - 601)), START) == 'refreshed'
    assert proof.label(facts(make_token(iat=START + 5)), START) == 'issued'


def test_allowance_is_ten_minutes():
    assert proof.ALLOWANCE_SECONDS == 600


@pytest.mark.parametrize('verdict, broker, tried, step', [
    ('proven', False, False, 'succeed'),
    ('proven', True, False, 'succeed'),
    ('same', False, False, 'fail'),
    ('stale', False, False, 'fail'),
    ('same', True, False, 'renew_broker'),
    ('stale', True, False, 'renew_broker'),
    ('same', True, True, 'fail'),
    ('stale', True, True, 'fail'),
    ('unreadable', True, False, 'fail'),
])
def test_next_step(verdict, broker, tried, step):
    assert proof.next_step(verdict, broker, tried) == step


def test_broker_claims():
    assert json.loads(proof.broker_claims(False)) == {
        'access_token': {'xms_cc': {'values': ['CP1']}}}
    assert proof.broker_claims(True) is None
