"""Refreshing the token of a signed-in user account."""

import re

import pytest

from azext_refresh_token import proof
from conftest import TYPICAL_RUN_SECONDS, payload_of
from fake_entra import HOME_TENANT

pytestmark = pytest.mark.integration

ARM_SCOPE = 'https://management.example.test//.default'
GRAPH_SCOPE = 'https://graph.example.test//.default'
DEVICE_CODE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'


def sign_in_with_old_cached_token(az, fake):
    """Sign in and cache an Azure Resource Manager token that looks older than the allowance."""
    fake.state.clock_offset_seconds = -1800
    az.login_user()
    first = az.token()
    fake.state.clock_offset_seconds = 0
    return first


def test_refresh_replaces_cached_arm_token(az, fake):
    first = sign_in_with_old_cached_token(az, fake)
    before = proof.fingerprint(first['accessToken'])
    forced_before = len(fake.state.requests_for('refresh_token', ARM_SCOPE))

    result, output = az.refresh()

    assert result.returncode == 0, result.stderr
    assert output['status'] == 'refreshed'
    assert output['previousFingerprint'] == before
    assert output['fingerprint'] != before
    assert output['scopes'] == [ARM_SCOPE]
    assert output['tenant'] == HOME_TENANT
    assert az.fingerprint() == output['fingerprint']
    forced = fake.state.requests_for('refresh_token', ARM_SCOPE)[forced_before:]
    assert len(forced) == 1
    assert 'xms_cc' in forced[0].claims


def test_new_token_carries_changed_groups(az, fake):
    sign_in_with_old_cached_token(az, fake)
    new_group = '99999999-9999-4999-8999-999999999999'
    sign_in_grants = len(fake.state.requests_for(DEVICE_CODE_GRANT))
    fake.state.groups = fake.state.groups + [new_group]

    result, _ = az.refresh()

    assert result.returncode == 0, result.stderr
    assert new_group in payload_of(az.token()['accessToken'])['groups']
    assert len(fake.state.requests_for(DEVICE_CODE_GRANT)) == sign_in_grants


def test_output_none_and_query(az, fake):
    sign_in_with_old_cached_token(az, fake)

    quiet = az.run('account', 'refresh-token', '-o', 'none')
    assert quiet.returncode == 0, quiet.stderr
    assert quiet.stdout.strip() == ''

    queried = az.run('account', 'refresh-token', '--query', 'fingerprint', '-o', 'tsv')
    assert queried.returncode == 0, queried.stderr
    assert re.fullmatch(r'[0-9a-f]{12}', queried.stdout.strip())


def test_typical_run_is_fast(az, fake):
    sign_in_with_old_cached_token(az, fake)
    result, _ = az.refresh()
    assert result.returncode == 0, result.stderr
    assert result.seconds < TYPICAL_RUN_SECONDS


def test_refresh_changes_no_configuration_or_accounts(az, fake):
    sign_in_with_old_cached_token(az, fake)
    config_file = az.environment['AZURE_CONFIG_DIR'] + '/config'

    def state():
        try:
            with open(config_file, 'rb') as handle:
                configuration = handle.read()
        except FileNotFoundError:
            configuration = b''
        return (configuration, az.ok('account', 'list', '-o', 'json').stdout,
                az.ok('cloud', 'show', '-o', 'json').stdout)

    before = state()
    result, _ = az.refresh()
    assert result.returncode == 0, result.stderr
    assert state() == before


def test_uncached_audience_is_issued(az, fake):
    az.login_user()
    requests_before = len(fake.state.requests_for('refresh_token', GRAPH_SCOPE))

    result, output = az.refresh('--resource-type', 'ms-graph')

    assert result.returncode == 0, result.stderr
    assert output['status'] == 'issued'
    assert output['previousFingerprint'] != output['fingerprint']
    assert len(fake.state.requests_for('refresh_token', GRAPH_SCOPE)) - requests_before == 2
    assert az.fingerprint('--resource-type', 'ms-graph') == output['fingerprint']


def test_token_cached_seconds_before_is_still_renewed(az, fake):
    az.login_user()
    cached = az.fingerprint()

    result, output = az.refresh()

    assert result.returncode == 0, result.stderr
    assert output['status'] in ('issued', 'refreshed')
    assert output['fingerprint'] != cached
    assert az.fingerprint() == output['fingerprint']


def test_token_cached_half_a_minute_before_is_refreshed(az, fake):
    # Signing in caches the Azure Resource Manager token, so it is issued while the clock is behind.
    fake.state.clock_offset_seconds = -30
    try:
        az.login_user()
        cached = az.fingerprint()
    finally:
        fake.state.clock_offset_seconds = 0

    result, output = az.refresh()

    assert result.returncode == 0, result.stderr
    assert output['status'] == 'refreshed'
    assert output['previousFingerprint'] == cached
    assert output['fingerprint'] != cached
    assert az.fingerprint() == output['fingerprint']
