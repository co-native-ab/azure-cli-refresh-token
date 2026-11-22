"""Refreshing the token of a signed-in service principal."""

import pytest

from fake_entra import HOME_TENANT

pytestmark = pytest.mark.integration

ARM_SCOPE = 'https://management.example.test//.default'


def test_refresh_service_principal(az, fake):
    fake.state.clock_offset_seconds = -1800
    az.login_service_principal()
    before = az.fingerprint()
    fake.state.clock_offset_seconds = 0
    grants_before = len(fake.state.requests_for('client_credentials', ARM_SCOPE))

    result, output = az.refresh()

    assert result.returncode == 0, result.stderr
    assert output['status'] == 'refreshed'
    assert output['previousFingerprint'] == before
    assert output['fingerprint'] != before
    assert output['tenant'] == HOME_TENANT
    forced = fake.state.requests_for('client_credentials', ARM_SCOPE)[grants_before:]
    assert len(forced) == 1
    assert 'xms_cc' in forced[0].claims
    assert az.fingerprint() == output['fingerprint']
