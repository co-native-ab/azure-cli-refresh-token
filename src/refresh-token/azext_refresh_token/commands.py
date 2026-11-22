# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------


def load_command_table(self, _):
    with self.command_group('account') as g:
        g.custom_command('refresh-token', 'refresh_token')
