"""``--show-claims`` adds the payload of the new token, and nothing else from it."""

import json

import pytest

from conftest import assert_no_token_leak, payload_of

pytestmark = pytest.mark.integration


def sign_in_with_old_token(az, fake):
    fake.state.clock_offset_seconds = -1800
    az.login_user()
    az.token()
    fake.state.clock_offset_seconds = 0


def test_show_claims_returns_payload_of_new_token(az, fake):
    sign_in_with_old_token(az, fake)
    new_group = '99999999-9999-4999-8999-999999999999'
    fake.state.groups = fake.state.groups + [new_group]

    result, output = az.refresh('--show-claims')

    assert result.returncode == 0, result.stderr
    assert output['claims'] == payload_of(az.token()['accessToken'])
    assert new_group in output['claims']['groups']
    assert_no_token_leak(fake, result.stdout, result.stderr)


def test_no_claims_without_flag(az, fake):
    sign_in_with_old_token(az, fake)

    result, output = az.refresh()

    assert result.returncode == 0, result.stderr
    assert 'claims' not in output
    payload = payload_of(az.token()['accessToken'])
    for value in (payload['uti'], payload['oid'], payload['upn']):
        assert value not in result.stdout


def test_claims_not_logged_with_debug(az, fake):
    sign_in_with_old_token(az, fake)

    result, output = az.refresh('--show-claims', '--debug')

    assert result.returncode == 0, result.stderr
    unique = output['claims']['uti']
    assert result.stdout.count(unique) == 1
    assert unique not in result.stderr
    assert json.loads(result.stdout)['claims']['uti'] == unique
