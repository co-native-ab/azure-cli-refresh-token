"""No token, in any form, reaches the output or the debug log."""

import pytest

from conftest import assert_no_token_leak
from fake_entra import OTHER_TENANT

pytestmark = pytest.mark.integration

SUCCESS_CASES = [
    ('default', [], 'user'),
    ('ms-graph', ['--resource-type', 'ms-graph'], 'user'),
    ('other-tenant', ['--tenant', OTHER_TENANT], 'user'),
    ('service-principal', [], 'servicePrincipal'),
]


@pytest.mark.parametrize('debug', [False, True], ids=['plain', 'debug'])
@pytest.mark.parametrize('name, arguments, account', SUCCESS_CASES,
                         ids=[case[0] for case in SUCCESS_CASES])
def test_successful_refresh_leaks_no_token(az, fake, name, arguments, account, debug):
    if account == 'user':
        az.login_user()
    else:
        az.login_service_principal()
    az.token(*arguments)
    extra = ['--debug'] if debug else []

    result, _ = az.refresh(*arguments, *extra)

    assert result.returncode == 0, result.stderr
    assert_no_token_leak(fake, result.stdout, result.stderr)


FAILURE_MODES = ['interaction_required', 'same_token', 'stale_token', 'opaque_token', 'bad_secret']


@pytest.mark.parametrize('debug', [False, True], ids=['plain', 'debug'])
@pytest.mark.parametrize('mode', FAILURE_MODES)
def test_failed_refresh_leaks_no_token(az, fake, mode, debug):
    if mode == 'bad_secret':
        az.login_service_principal()
    else:
        az.login_user()
    az.token()
    fake.state.mode = mode
    extra = ['--debug'] if debug else []

    if mode == 'opaque_token':
        # The opaque token is cached by a plain call, so the refresh fails before asking again.
        az.token('--resource-type', 'ms-graph')
        extra += ['--resource-type', 'ms-graph']

    result, _ = az.refresh(*extra)

    assert result.returncode == 1
    assert_no_token_leak(fake, result.stdout, result.stderr)
