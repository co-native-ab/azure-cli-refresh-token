import pytest

from azext_refresh_token import broker
from fake_pymsalruntime import FakeModule

CLIENT_ID = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
AUTHORITY = 'https://login.example.test/11111111-1111-4111-8111-111111111111'
SCOPES = ['https://management.example.test//.default']
CLAIMS = '{"access_token": {"xms_cc": {"values": ["CP1"]}}}'


def renewal(module, timeout=5):
    return broker.BrokerRenewal(module, CLIENT_ID, timeout=timeout)


def renew(module, platform='win32', claims=CLAIMS, username='user@example.test', timeout=5):
    renewal(module, timeout).renew(AUTHORITY, username, SCOPES, claims, 'the-old-token', platform)


def test_renews_with_the_expected_parameters():
    module = FakeModule()
    renew(module)
    (parameters,) = module.parameters
    assert module.discovered_for == [CLIENT_ID]
    assert parameters.client_id == CLIENT_ID
    assert parameters.authority == AUTHORITY
    assert parameters.scopes == SCOPES
    assert parameters.claims == CLAIMS
    assert parameters.token_to_renew == 'the-old-token'
    assert parameters.redirect_uri == 'https://login.microsoftonline.com/common/oauth2/nativeclient'
    assert len(module.acquired_for) == 1


def test_macos_uses_its_redirect_uri():
    module = FakeModule()
    renew(module, platform='darwin')
    assert module.parameters[0].redirect_uri == 'msauth.com.msauth.unsignedapp://auth'


def test_no_claims_are_set_when_there_are_none():
    module = FakeModule()
    renew(module, claims=None)
    assert module.parameters[0].claims is None


def test_user_name_match_ignores_case():
    module = FakeModule(user_names=('USER@Example.Test',))
    renew(module)
    assert len(module.acquired_for) == 1


@pytest.mark.parametrize('names, found', [((), 0), (('user@example.test', 'user@EXAMPLE.test'), 2),
                                           (('someone@example.test',), 0)])
def test_zero_or_several_matching_accounts_fail(names, found):
    module = FakeModule(user_names=names)
    with pytest.raises(broker.BrokerAccountError) as error:
        renew(module)
    assert error.value.found == found
    assert module.acquired_for == []


def test_interaction_required_is_reported():
    module = FakeModule()
    module.auth_error = module.error(module.Response_Status.Status_InteractionRequired, 7)
    with pytest.raises(broker.BrokerInteractionRequired):
        renew(module)


def test_other_broker_errors_are_failures():
    module = FakeModule()
    module.auth_error = module.error(module.Response_Status.Status_Error, 42)
    with pytest.raises(broker.BrokerFailure) as error:
        renew(module)
    assert not isinstance(error.value, broker.BrokerInteractionRequired)
    assert '42' in str(error.value)


def test_account_discovery_error_is_a_failure():
    module = FakeModule()
    module.discover_error = module.error(module.Response_Status.Status_Error, 5)
    with pytest.raises(broker.BrokerFailure):
        renew(module)
    assert module.acquired_for == []


def test_a_broker_that_never_answers_is_cancelled_after_the_timeout():
    module = FakeModule(answer=False)
    with pytest.raises(broker.BrokerFailure) as error:
        renew(module, timeout=0.05)
    assert 'did not answer' in str(error.value)
    assert module.handles[0].cancelled
