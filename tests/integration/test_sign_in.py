"""The fake identity provider and the test harness work with the real Azure CLI."""

import pytest

from azext_refresh_token import proof
from conftest import assert_no_token_leak
from fake_entra import HOME_TENANT
from fake_entra import TENANTS

pytestmark = pytest.mark.integration


def test_user_signs_in_by_device_code_without_input(az, fake):
    az.register_cloud()
    result = az.ok('login', '--use-device-code', '--tenant', HOME_TENANT)
    account = az.json('account', 'show')
    assert account['user']['name'] == fake.state.username
    assert account['user']['type'] == 'user'
    assert account['tenantId'] == HOME_TENANT
    assert account['id'] == TENANTS[HOME_TENANT].subscription_id
    assert_no_token_leak(fake, result.stdout, result.stderr)


def test_service_principal_signs_in_by_secret(az, fake):
    az.login_service_principal()
    account = az.json('account', 'show')
    assert account['user']['name'] == fake.state.app_id
    assert account['user']['type'] == 'servicePrincipal'


def test_get_access_token_returns_a_token_the_fake_issued(az, fake):
    az.login_user()
    result = az.ok('account', 'get-access-token', '-o', 'json')
    import json
    token = json.loads(result.stdout)['accessToken']
    arm_tokens = [issued for issued in fake.state.issued_tokens('access')
                  if issued.scope == 'https://management.example.test//.default']
    assert proof.fingerprint(token) in [proof.fingerprint(issued.text) for issued in arm_tokens]
    assert_no_token_leak(fake, result.stderr)
