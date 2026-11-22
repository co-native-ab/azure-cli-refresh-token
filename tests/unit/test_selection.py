import types

import pytest

from azext_refresh_token import selection

ENDPOINTS = types.SimpleNamespace(
    ossrdbms_resource_id='https://oss.example.test/',
    active_directory_resource_id='https://arm.example.test/',
    active_directory_graph_resource_id='https://aadgraph.example.test/',
    microsoft_graph_resource_id='https://graph.example.test/',
    batch_resource_id='https://batch.example.test/',
    media_resource_id='https://media.example.test/',
    active_directory_data_lake_resource_id='https://datalake.example.test/',
)

ARM = ENDPOINTS.active_directory_resource_id


def test_resource_types_keep_the_order_of_get_access_token():
    assert selection.RESOURCE_TYPES == [
        'oss-rdbms', 'arm', 'aad-graph', 'ms-graph', 'batch', 'media', 'data-lake']


@pytest.mark.parametrize('resource_type, expected', [
    ('oss-rdbms', 'https://oss.example.test/'),
    ('arm', 'https://arm.example.test/'),
    ('aad-graph', 'https://aadgraph.example.test/'),
    ('ms-graph', 'https://graph.example.test/'),
    ('batch', 'https://batch.example.test/'),
    ('media', 'https://media.example.test/'),
    ('data-lake', 'https://datalake.example.test/'),
])
def test_every_resource_type_maps_to_its_endpoint(resource_type, expected):
    assert selection.resolve_resource(None, resource_type, ENDPOINTS) == expected


def test_resource_wins_over_resource_type():
    assert selection.resolve_resource('https://own.example.test', 'ms-graph', ENDPOINTS) \
        == 'https://own.example.test'


def test_no_resource_and_no_type_resolves_to_nothing():
    assert selection.resolve_resource(None, None, ENDPOINTS) is None


def test_resource_type_without_endpoint_behaves_as_no_resource():
    endpoints = types.SimpleNamespace(microsoft_graph_resource_id=None)
    resource = selection.resolve_resource(None, 'ms-graph', endpoints)
    assert resource is None
    assert selection.resolve_scopes(None, resource, ARM) == [ARM + '/.default']


def test_default_scope_is_resource_manager():
    assert selection.resolve_scopes(None, None, ARM) == ['https://arm.example.test//.default']
    assert selection.resolve_scopes([], None, ARM) == ['https://arm.example.test//.default']


def test_resource_becomes_default_scope():
    assert selection.resolve_scopes(None, 'https://own.example.test', ARM) \
        == ['https://own.example.test/.default']


def test_scope_wins_over_resource():
    assert selection.resolve_scopes(['a/.default'], 'https://own.example.test', ARM) \
        == ['a/.default']


def test_several_scopes_are_kept_as_given():
    assert selection.resolve_scopes(['b/.default', 'a/.default'], None, ARM) \
        == ['b/.default', 'a/.default']


def test_subscription_with_tenant_is_rejected_with_the_message_of_get_access_token():
    with pytest.raises(ValueError) as error:
        selection.check_conflicts('sub', 'tenant')
    assert str(error.value) == 'Please specify only one of subscription and tenant, not both'


@pytest.mark.parametrize('subscription, tenant', [(None, None), ('sub', None), (None, 'tenant')])
def test_other_combinations_are_accepted(subscription, tenant):
    selection.check_conflicts(subscription, tenant)


@pytest.mark.parametrize('account, in_cloud_shell, kind', [
    ({'user': {'name': 'user@example.test', 'type': 'user'}}, False, 'user'),
    ({'user': {'name': 'app', 'type': 'servicePrincipal'}}, False, 'servicePrincipal'),
    ({'user': {'name': 'systemAssignedIdentity', 'type': 'servicePrincipal'}}, False,
     'managedIdentity'),
    ({'user': {'name': 'userAssignedIdentity', 'type': 'servicePrincipal'}}, False,
     'managedIdentity'),
    ({'user': {'name': 'cloud', 'type': 'user', 'cloudShellID': True}}, True, 'cloudShell'),
    ({'user': {'name': 'cloud', 'type': 'user', 'cloudShellID': True}}, False, 'user'),
    ({'user': {'name': 'x', 'type': 'somethingElse'}}, False, 'unsupported'),
    ({}, False, 'unsupported'),
])
def test_account_kind(account, in_cloud_shell, kind):
    assert selection.account_kind(account, in_cloud_shell) == kind


def test_cloud_shell_is_checked_before_the_user_type():
    account = {'user': {'name': 'systemAssignedIdentity', 'type': 'user', 'cloudShellID': True}}
    assert selection.account_kind(account, True) == 'cloudShell'


@pytest.mark.parametrize('kind, supported', [
    ('user', True), ('servicePrincipal', True), ('managedIdentity', False),
    ('cloudShell', False), ('unsupported', False),
])
def test_only_users_and_service_principals_are_supported(kind, supported):
    assert selection.is_supported(kind) is supported


def test_tenant_comparison_ignores_case():
    assert selection.is_other_tenant('ABC', 'abc') is False
    assert selection.is_other_tenant('abc', 'def') is True
    assert selection.is_other_tenant(None, 'def') is False


@pytest.mark.parametrize('platform, machine, kind, windows, mac, expected', [
    ('win32', 'AMD64', 'user', True, False, True),
    ('win32', 'AMD64', 'user', False, False, False),
    ('darwin', 'arm64', 'user', True, True, True),
    ('darwin', 'arm64', 'user', True, False, False),
    ('darwin', 'x86_64', 'user', True, True, False),
    ('linux', 'x86_64', 'user', True, True, False),
    ('win32', 'AMD64', 'servicePrincipal', True, True, False),
    ('darwin', 'arm64', 'servicePrincipal', True, True, False),
])
def test_broker_in_use(platform, machine, kind, windows, mac, expected):
    assert selection.broker_in_use(platform, machine, kind, windows, mac) is expected


def test_broker_setting_names():
    assert selection.broker_setting('win32') == 'core.enable_broker_on_windows'
    assert selection.broker_setting('darwin') == 'core.enable_broker_on_mac'


OWN = ['Check the secret or certificate.']
OURS = 'Run az login.'


@pytest.mark.parametrize('kind, codes, expected', [
    (selection.KIND_SERVICE_PRINCIPAL, [7000215], OWN + [OURS]),
    (selection.KIND_SERVICE_PRINCIPAL, [70000, 7000215], OWN + [OURS]),
    (selection.KIND_SERVICE_PRINCIPAL, [7000222], [OURS]),
    (selection.KIND_SERVICE_PRINCIPAL, [], [OURS]),
    (selection.KIND_SERVICE_PRINCIPAL, None, [OURS]),
    (selection.KIND_USER, [7000215], [OURS]),
    (selection.KIND_USER, [50076], [OURS]),
])
def test_choose_recommendations(kind, codes, expected):
    assert selection.choose_recommendations(kind, codes, OWN, OURS) == expected
