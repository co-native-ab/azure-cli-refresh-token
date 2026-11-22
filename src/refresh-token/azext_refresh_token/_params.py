# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

from azext_refresh_token.selection import RESOURCE_TYPES


def load_arguments(self, _):
    from azure.cli.core.api import get_subscription_id_list
    from azure.cli.core.commands.parameters import get_enum_type

    with self.argument_context('account refresh-token') as c:
        c.argument('resource_type', get_enum_type(RESOURCE_TYPES), options_list=['--resource-type'],
                   help='Type of well-known resource, resolved against the active cloud.')
        c.argument('resource', options_list=['--resource'],
                   help='Azure resource endpoint in Microsoft Entra v1.0. Overrides --resource-type.')
        c.argument('scopes', options_list=['--scope'], nargs='*',
                   help='Space-separated scopes in Microsoft Entra v2.0. Overrides --resource. '
                        'Default to Azure Resource Manager.')
        c.argument('tenant', options_list=['--tenant', '-t'],
                   help='Tenant ID for which the token is refreshed. Only available for user and '
                        'service principal accounts.')
        c.argument('subscription', options_list=['--subscription', '-s', '--name', '-n'],
                   completer=get_subscription_id_list, help='Name or ID of subscription.')
        c.argument('show_claims', options_list=['--show-claims'], action='store_true',
                   help='Add the decoded payload (claims) of the new token to the output. '
                        'The payload holds personal data, so it is shown only when asked for. '
                        'Microsoft Entra ID sets the issue time (iat, also shown as issuedAt) '
                        'about 5 minutes before it actually issues the token.')
        c.ignore('_subscription')
