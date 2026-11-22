"""``az account refresh-token`` replaces the token ``az account get-access-token`` returns."""

import re

import pytest

from azext_refresh_token import proof, selection
from conftest import payload_of
from fake_entra import HOME_TENANT, OTHER_TENANT
from fake_entra import TENANTS

pytestmark = pytest.mark.integration

HOME_SUBSCRIPTION = TENANTS[HOME_TENANT].subscription_id

CASES = (
    [('default', [])]
    + [('type-' + resource_type, ['--resource-type', resource_type])
       for resource_type in selection.RESOURCE_TYPES]
    + [
        ('resource', ['--resource', 'https://custom.example.test']),
        ('scope', ['--scope', 'https://custom-scope.example.test/.default']),
        ('two-scopes', ['--scope', 'https://scope-one.example.test/.default',
                        'https://scope-two.example.test/.default']),
        ('home-tenant', ['--tenant', HOME_TENANT]),
        ('other-tenant', ['--tenant', OTHER_TENANT]),
        ('subscription', ['--subscription', HOME_SUBSCRIPTION]),
    ]
)


def test_refresh_replaces_the_token_get_access_token_returns(az, fake):
    az.login_user()
    primed = {}
    initial = {}
    for name, arguments in CASES:
        seen = len(fake.state.requests)
        initial[name] = az.fingerprint(*arguments)
        asked = fake.state.requests[seen:]
        primed[name] = [(request.tenant, request.scope) for request in asked
                        if request.grant_type == 'refresh_token']

    for name, arguments in CASES:
        seen = len(fake.state.requests)
        result, output = az.refresh(*arguments)
        assert result.returncode == 0, '{}: {}'.format(name, result.stderr)
        asked = [(request.tenant, request.scope) for request in fake.state.requests[seen:]
                 if request.grant_type == 'refresh_token']

        # The same scope and tenant that get-access-token asked for, in a single request.
        assert len(asked) == 1, name
        if primed[name]:
            assert asked == primed[name], name
        token = az.token(*arguments)
        new_fingerprint = proof.fingerprint(token['accessToken'])
        assert new_fingerprint == output['fingerprint'], name
        assert output['previousFingerprint'] != output['fingerprint'], name
        assert asked[0] == (payload_of(token['accessToken'])['tid'], ' '.join(output['scopes'])), name
        assert ('subscription' in output) == (not any(a == '--tenant' for a in arguments)), name

        # Every other token the cache holds is unchanged.
        replaced = initial[name]
        for other, other_arguments in CASES:
            if initial[other] == replaced:
                initial[other] = new_fingerprint
                continue
            assert az.fingerprint(*other_arguments) == initial[other], (name, other)


def allowed_values(stderr):
    """The values the Azure CLI lists for an invalid ``--resource-type``; its wording differs
    between releases ("Allowed values: a, b." or "choose from 'a', 'b'")."""
    match = re.search(r'(?:Allowed values:|choose from)\s*(.*?)(?:\.\s|\)|$)', stderr, re.S)
    assert match, stderr
    return [value.strip("' \n") for value in match.group(1).split(',')]


def test_resource_type_values_match_get_access_token(az):
    for command in ('get-access-token', 'refresh-token'):
        result = az.run('account', command, '--resource-type', 'not-a-resource-type')
        assert result.returncode == 2, command
    expected = allowed_values(az.run('account', 'get-access-token', '--resource-type', 'x').stderr)
    actual = allowed_values(az.run('account', 'refresh-token', '--resource-type', 'x').stderr)
    assert actual == expected
    assert actual == selection.RESOURCE_TYPES


def test_subscription_with_tenant_rejected_like_get_access_token(az):
    arguments = ['--subscription', HOME_SUBSCRIPTION, '--tenant', HOME_TENANT]
    expected = az.run('account', 'get-access-token', *arguments)
    actual = az.run('account', 'refresh-token', *arguments)
    assert expected.returncode == actual.returncode == 1
    message = 'Please specify only one of subscription and tenant, not both'
    assert message in expected.stderr
    assert message in actual.stderr
