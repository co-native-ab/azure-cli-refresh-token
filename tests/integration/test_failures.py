"""Every failure ends with a non-zero exit code, an error that says what to do, and no prompt."""

import json
import pathlib

import pytest

from conftest import TYPICAL_RUN_SECONDS
from fake_entra import HOME_TENANT

pytestmark = pytest.mark.integration

ARM_SCOPE = 'https://management.example.test//.default'
GRAPH_SCOPE = 'https://graph.example.test//.default'


def refresh_fails(az, *arguments):
    result = az.run('account', 'refresh-token', '-o', 'json', *arguments)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stdout.strip() == ''
    return result


def test_not_signed_in(az):
    az.register_cloud()
    result = refresh_fails(az)
    assert 'az login' in result.stderr


def test_unknown_subscription(az):
    az.login_user()
    result = refresh_fails(az, '--subscription', 'no-such-subscription')
    assert "Subscription 'no-such-subscription' not found" in result.stderr


def test_interaction_required_names_az_login(az, fake):
    az.login_user()
    az.token()
    fake.state.mode = 'interaction_required'

    result = refresh_fails(az)

    assert result.seconds < TYPICAL_RUN_SECONDS
    assert 'az login --tenant "{}"'.format(HOME_TENANT) in result.stderr
    assert ARM_SCOPE in result.stderr
    for text in ('device code', 'browser'):
        assert text not in result.stderr.lower()


def test_service_principal_bad_secret_names_az_login(az, fake):
    az.login_service_principal()
    az.token()
    fake.state.mode = 'bad_secret'

    result = refresh_fails(az)

    assert 'az login --service-principal --username "{}"'.format(fake.state.app_id) in result.stderr
    # The Azure CLI's own explanation of this error is kept next to ours.
    assert '--certificate' in result.stderr


def test_same_token_is_not_reported_as_refreshed(az, fake):
    az.login_user()
    az.token()
    fake.state.mode = 'same_token'

    result = refresh_fails(az)

    assert 'not renewed' in result.stderr
    assert 'refreshed' not in result.stdout and 'issued' not in result.stdout


def test_stale_token_mentions_clock(az, fake):
    az.login_user()
    az.token()
    fake.state.mode = 'stale_token'

    result = refresh_fails(az)

    assert 'not renewed' in result.stderr
    assert 'clock' in result.stderr


def test_opaque_token_cannot_be_proven(az, fake):
    az.login_user()
    fake.state.mode = 'opaque_token'
    az.token('--resource-type', 'ms-graph')
    requests_before = len(fake.state.requests)

    result = refresh_fails(az, '--resource-type', 'ms-graph')

    assert 'cannot be proven' in result.stderr
    assert len(fake.state.requests) == requests_before


def test_new_token_without_issue_time_cannot_be_proven(az, fake):
    az.login_user()
    az.token()
    fake.state.mode = 'opaque_token'

    result = refresh_fails(az)

    assert 'issue time cannot be read' in result.stderr
    assert 'Nothing was requested' not in result.stderr


def test_managed_identity_account_is_rejected_up_front(az, fake):
    az.login_user()
    profile_path = pathlib.Path(az.environment['AZURE_CONFIG_DIR']) / 'azureProfile.json'
    profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
    for subscription in profile['subscriptions']:
        subscription['user']['name'] = 'systemAssignedIdentity'
    profile_path.write_text(json.dumps(profile), encoding='utf-8')
    requests_before = len(fake.state.requests)

    result = refresh_fails(az)

    assert 'managed identity' in result.stderr
    assert 'cannot be refreshed' in result.stderr
    assert len(fake.state.requests) == requests_before

