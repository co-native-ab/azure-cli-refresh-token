# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

"""Deciding which token to refresh.

This module is pure: it uses only the standard library and does no network, file system, clock or
Azure CLI access. The values and rules mirror ``az account get-access-token`` so that both commands
pick the same token for the same arguments.
"""

# The ``--resource-type`` values of ``az account get-access-token`` and the cloud endpoint
# attribute each one resolves to. A test compares this table with the installed Azure CLI.
RESOURCE_TYPE_ENDPOINTS = {
    'oss-rdbms': 'ossrdbms_resource_id',
    'arm': 'active_directory_resource_id',
    'aad-graph': 'active_directory_graph_resource_id',
    'ms-graph': 'microsoft_graph_resource_id',
    'batch': 'batch_resource_id',
    'media': 'media_resource_id',
    'data-lake': 'active_directory_data_lake_resource_id',
}

RESOURCE_TYPES = list(RESOURCE_TYPE_ENDPOINTS)

SUBSCRIPTION_AND_TENANT_MESSAGE = 'Please specify only one of subscription and tenant, not both'

KIND_USER = 'user'
KIND_SERVICE_PRINCIPAL = 'servicePrincipal'
KIND_MANAGED_IDENTITY = 'managedIdentity'
KIND_CLOUD_SHELL = 'cloudShell'
KIND_UNSUPPORTED = 'unsupported'

_MANAGED_IDENTITY_NAMES = ('systemAssignedIdentity', 'userAssignedIdentity')

BROKER_SETTING_WINDOWS = 'core.enable_broker_on_windows'
BROKER_SETTING_MAC = 'core.enable_broker_on_mac'


def check_conflicts(subscription, tenant):
    """Reject the argument combination that ``get-access-token`` rejects, with the same message."""
    if subscription and tenant:
        raise ValueError(SUBSCRIPTION_AND_TENANT_MESSAGE)


def resolve_resource(resource, resource_type, endpoints):
    """The resource to refresh: ``--resource`` wins over ``--resource-type``.

    ``endpoints`` is the active cloud's endpoints object. The attribute for a resource type may be
    missing or None, which behaves as if no resource was given.
    """
    if resource is None and resource_type:
        return getattr(endpoints, RESOURCE_TYPE_ENDPOINTS[resource_type], None)
    return resource


def resolve_scopes(scopes, resource, arm_resource_id):
    """The scopes to request: ``--scope`` wins over the resource, which wins over Resource Manager."""
    if scopes:
        return list(scopes)
    if resource:
        return [resource + '/.default']
    return [arm_resource_id + '/.default']


def account_kind(account, in_cloud_shell):
    """Classify the account dictionary the Azure CLI keeps for a subscription."""
    user = account.get('user') or {}
    if in_cloud_shell and user.get('cloudShellID'):
        return KIND_CLOUD_SHELL
    if user.get('name') in _MANAGED_IDENTITY_NAMES:
        return KIND_MANAGED_IDENTITY
    if user.get('type') == 'user':
        return KIND_USER
    if user.get('type') == 'servicePrincipal':
        return KIND_SERVICE_PRINCIPAL
    return KIND_UNSUPPORTED


def is_supported(kind):
    """Whether tokens of this kind of account can be refreshed."""
    return kind in (KIND_USER, KIND_SERVICE_PRINCIPAL)


def is_other_tenant(tenant, account_tenant):
    """Whether ``--tenant`` names a tenant other than the account's own."""
    if not tenant:
        return False
    return tenant.lower() != (account_tenant or '').lower()


def broker_in_use(platform, machine, kind, enable_on_windows, enable_on_mac):
    """Whether the Azure CLI may be using an operating system broker for this account.

    Only user accounts sign in through a broker. The macOS broker is available on Apple silicon only.
    """
    if kind != KIND_USER:
        return False
    if platform == 'win32':
        return bool(enable_on_windows)
    if platform == 'darwin':
        return machine == 'arm64' and bool(enable_on_mac)
    return False


def broker_setting(platform):
    """The Azure CLI setting that turns the broker off on this platform."""
    return BROKER_SETTING_MAC if platform == 'darwin' else BROKER_SETTING_WINDOWS
