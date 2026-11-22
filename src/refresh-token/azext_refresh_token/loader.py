# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core import AzCommandsLoader

import azext_refresh_token._help  # pylint: disable=unused-import


class RefreshTokenCommandsLoader(AzCommandsLoader):

    def __init__(self, cli_ctx=None):
        from azure.cli.core.commands import CliCommandType
        custom_command_type = CliCommandType(operations_tmpl='azext_refresh_token.custom#{}')
        super().__init__(cli_ctx=cli_ctx, custom_command_type=custom_command_type)

    def load_command_table(self, args):
        from azext_refresh_token.commands import load_command_table
        load_command_table(self, args)
        return self.command_table

    def load_arguments(self, command):
        from azext_refresh_token._params import load_arguments
        load_arguments(self, command)
