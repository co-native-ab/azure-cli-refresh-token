import json

import pytest

from azext_refresh_token import proof, result
from test_proof import START, make_token

REQUIRED = {'status', 'scopes', 'audience', 'tenant', 'previousFingerprint', 'fingerprint',
            'issuedAt', 'expiresOn', 'expires_on'}
OPTIONAL = {'subscription', 'claims'}
TIME_PATTERN = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
FINGERPRINT_PATTERN = r'^[0-9a-f]{12}$'

TOKEN = make_token(iat=START, aud='https://arm.example.test/', tid='tenant', exp=START + 4000,
                   groups=['g1'])
FACTS = proof.inspect(TOKEN)


def build(**overrides):
    arguments = dict(label='refreshed', scopes=['https://arm.example.test//.default'],
                     final_facts=FACTS, tenant='tenant', subscription='sub',
                     start_fingerprint='0123456789ab', expires_on=START + 3600,
                     show_claims=False)
    arguments.update(overrides)
    return result.build(**arguments)


def test_output_has_exactly_the_documented_fields():
    output = build()
    assert set(output) == REQUIRED | {'subscription'}
    output = build(show_claims=True)
    assert set(output) == REQUIRED | OPTIONAL


def test_values_and_patterns():
    import re
    output = build()
    assert re.match(FINGERPRINT_PATTERN, output['fingerprint'])
    assert re.match(FINGERPRINT_PATTERN, output['previousFingerprint'])
    assert re.match(TIME_PATTERN, output['issuedAt'])
    assert re.match(TIME_PATTERN, output['expiresOn'])
    assert output['issuedAt'] == '2027-01-15T08:00:00Z'
    assert output['expiresOn'] == '2027-01-15T09:00:00Z'
    assert output['expires_on'] == START + 3600
    assert output['audience'] == 'https://arm.example.test/'
    assert output['status'] == 'refreshed'
    assert output['fingerprint'] == proof.fingerprint(TOKEN)


def test_subscription_is_omitted_without_one():
    assert 'subscription' not in build(subscription=None)


def test_claims_only_with_the_flag():
    assert 'claims' not in build()
    assert build(show_claims=True)['claims']['groups'] == ['g1']


def test_output_never_holds_the_token_or_its_segments():
    text = json.dumps(build(show_claims=True))
    header, payload, signature = TOKEN.split('.')
    for part in (TOKEN, header, payload, signature):
        assert part not in text


def test_unsupported_account_message_names_the_account_type():
    assert 'managed identity' in result.unsupported_account_message('managedIdentity')
    assert 'Cloud Shell' in result.unsupported_account_message('cloudShell')
    assert 'Nothing was requested' in result.unsupported_account_message('unsupported')


def test_login_command_for_a_user():
    command = result.login_command('user', 'tenant', ['a/.default', 'b/.default'], 'u@example.test')
    assert command == 'az login --tenant "tenant" --scope "a/.default" "b/.default"'


def test_login_command_for_a_service_principal():
    command = result.login_command('servicePrincipal', 'tenant', ['a/.default'], 'app-id')
    assert command == 'az login --service-principal --username "app-id" --tenant "tenant"'


def test_sign_in_recommendation_names_az_login():
    assert 'az login' in result.sign_in_required_recommendation('user', 't', ['s'], 'u')


def test_not_renewed_messages():
    same = result.not_renewed_same_message('0123456789ab')
    assert 'not renewed' in same and '0123456789ab' in same
    stale = result.not_renewed_stale_message(START - 3600)
    assert 'not renewed' in stale and 'clock' in stale and '10 minutes' in stale


def test_new_token_unreadable_message_differs_from_nothing_requested():
    message = result.new_token_unreadable_message('0123456789ab')
    assert 'issue time cannot be read' in message
    assert 'Nothing was requested' not in message


def test_sign_in_recommendation_says_signing_out_is_not_needed():
    assert 'do not need to sign out' in result.sign_in_required_recommendation('user', 't', ['s'], 'u')


def test_cannot_prove_message():
    message = result.cannot_prove_message()
    assert 'cannot be proven' in message and 'Nothing was requested' in message


@pytest.mark.parametrize('setting', ['core.enable_broker_on_windows', 'core.enable_broker_on_mac'])
def test_broker_messages_name_the_setting_and_leave_it_unchanged(setting):
    for message in (result.broker_sentence(setting),
                    result.broker_unavailable_message(setting, 'it timed out'),
                    result.broker_account_message(setting, 0),
                    result.broker_account_message(setting, 2)):
        assert setting in message
        assert 'does not change' in message
        assert 'az login' in message
