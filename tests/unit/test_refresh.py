"""The refresh sequence, tested without the Azure CLI or a broker."""

import base64
import json

import pytest

from azext_refresh_token import broker, refresh
from fake_pymsalruntime import FakeModule

START = 1_700_000_000
TENANT = '11111111-1111-4111-8111-111111111111'
SETTING = 'core.enable_broker_on_windows'


def make_token(label, iat=START, tenant=TENANT):
    """A readable token: three segments with a JSON payload. ``label`` makes it unique."""
    payload = {'iat': iat, 'aud': 'audience', 'label': label}
    if tenant is not None:
        payload['tid'] = tenant
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return f'header.{encoded}.signature'


class Current:
    def __init__(self, token):
        self.token = token


class Scenario:
    """Stands in for the Azure CLI. It hands out ``starting`` until the credential is forced, then
    ``after_force``; once the broker has renewed a token, a forced request returns ``after_renew``."""

    def __init__(self, starting, after_force, after_renew=None, renew_error=None):
        self.now = starting
        self.after_force = after_force
        self.after_renew = after_renew
        self.renew_error = renew_error
        self.forced = 0
        self.renewed = []

    def current(self):
        return Current(self.now)

    def force(self):
        self.forced += 1
        renewed = self.renewed and self.after_renew is not None
        self.now = self.after_renew if renewed else self.after_force

    def renew(self, token, tenant_id):
        self.renewed.append((token, tenant_id))
        if self.renew_error:
            raise self.renew_error


def run(scenario, use_broker=True):
    return refresh.run(start=START, current=scenario.current, force=scenario.force,
                       renew=scenario.renew, use_broker=use_broker, setting=SETTING)


def test_a_new_token_succeeds_without_the_broker():
    old, new = make_token('old', iat=START - 3600), make_token('new')
    scenario = Scenario(old, after_force=new)
    start_facts, final, final_facts = run(scenario)
    assert final.token == new
    assert start_facts.fingerprint != final_facts.fingerprint
    assert scenario.renewed == []


def test_the_broker_renews_the_starting_token_when_the_same_token_comes_back():
    old, new = make_token('old', iat=START - 3600), make_token('new')
    scenario = Scenario(old, after_force=old, after_renew=new)
    _, final, _ = run(scenario)
    assert scenario.renewed == [(old, TENANT)]
    assert final.token == new
    assert scenario.forced == 2


def test_the_broker_renews_the_token_the_forced_request_returned_when_it_is_stale():
    old = make_token('old', iat=START - 3600)
    stale = make_token('stale', iat=START - 7200, tenant='22222222-2222-4222-8222-222222222222')
    new = make_token('new')
    scenario = Scenario(old, after_force=stale, after_renew=new)
    _, final, _ = run(scenario)
    assert scenario.renewed == [(stale, '22222222-2222-4222-8222-222222222222')]
    assert final.token == new


def test_the_broker_is_used_at_most_once():
    old = make_token('old', iat=START - 3600)
    scenario = Scenario(old, after_force=old, after_renew=old)
    with pytest.raises(refresh.RefreshError) as failure:
        run(scenario)
    assert len(scenario.renewed) == 1
    assert scenario.forced == 2
    assert SETTING in str(failure.value)
    assert 'not renewed' in str(failure.value)


def test_a_broker_that_still_returns_a_stale_token_fails_naming_the_setting():
    old = make_token('old', iat=START - 3600)
    stale = make_token('stale', iat=START - 7200)
    scenario = Scenario(old, after_force=stale, after_renew=stale)
    with pytest.raises(refresh.RefreshError) as failure:
        run(scenario)
    assert len(scenario.renewed) == 1
    assert SETTING in str(failure.value) and 'clock' in str(failure.value)


def test_no_renewal_when_the_broker_is_not_in_use():
    old = make_token('old', iat=START - 3600)
    scenario = Scenario(old, after_force=old)
    with pytest.raises(refresh.RefreshError) as failure:
        run(scenario, use_broker=False)
    assert scenario.renewed == []
    assert scenario.forced == 1
    assert SETTING not in str(failure.value)


def test_nothing_is_requested_when_the_starting_token_is_unreadable():
    scenario = Scenario('opaque-token', after_force='opaque-token')
    with pytest.raises(refresh.RefreshError) as failure:
        run(scenario)
    assert scenario.forced == 0
    assert scenario.renewed == []
    assert 'Nothing was requested' in str(failure.value)


def test_a_new_token_without_an_issue_time_cannot_be_proven():
    scenario = Scenario(make_token('old', iat=START - 3600), after_force='opaque-token')
    with pytest.raises(refresh.RefreshError) as failure:
        run(scenario)
    assert scenario.renewed == []
    assert 'issue time cannot be read' in str(failure.value)
    assert 'Nothing was requested' not in str(failure.value)


def test_a_token_to_renew_without_a_tenant_fails_closed():
    old = make_token('old', iat=START - 3600, tenant=None)
    scenario = Scenario(old, after_force=old)
    with pytest.raises(refresh.RefreshError) as failure:
        run(scenario)
    assert scenario.renewed == []
    assert 'tenant' in str(failure.value) and SETTING in str(failure.value)


def test_interaction_required_from_the_broker_propagates():
    old = make_token('old', iat=START - 3600)
    scenario = Scenario(old, after_force=old,
                        renew_error=broker.BrokerInteractionRequired('sign in again'))
    with pytest.raises(broker.BrokerInteractionRequired):
        run(scenario)


def renew_with(module=None, load_error=None):
    def load_module():
        if load_error:
            raise load_error
        return module

    refresh.renew_in_broker(
        'the-token', TENANT, load_module=load_module, client_id='client',
        active_directory='https://login.example.test/', username='user@example.test',
        scopes=['scope'], claims=None, platform='win32', setting=SETTING)


def test_renewal_uses_the_authority_of_the_tenant():
    module = FakeModule()
    renew_with(module)
    assert module.parameters[0].authority == f'https://login.example.test/{TENANT}'
    assert module.parameters[0].token_to_renew == 'the-token'


def test_a_missing_broker_library_is_a_clear_error():
    with pytest.raises(refresh.RefreshError) as failure:
        renew_with(load_error=ImportError("No module named 'pymsalruntime'"))
    message = str(failure.value)
    assert 'broker library is not available' in message and SETTING in message


def test_a_broker_without_the_account_names_the_setting():
    with pytest.raises(refresh.RefreshError) as failure:
        renew_with(FakeModule(user_names=()))
    assert SETTING in str(failure.value)


def test_a_broker_error_names_the_setting():
    module = FakeModule()
    module.discover_error = module.error(module.Response_Status.Status_Error, 5)
    with pytest.raises(refresh.RefreshError) as failure:
        renew_with(module)
    assert SETTING in str(failure.value)


def test_a_broker_that_needs_a_sign_in_propagates_unchanged():
    module = FakeModule()
    module.auth_error = module.error(module.Response_Status.Status_InteractionRequired, 7)
    with pytest.raises(broker.BrokerInteractionRequired):
        renew_with(module)
