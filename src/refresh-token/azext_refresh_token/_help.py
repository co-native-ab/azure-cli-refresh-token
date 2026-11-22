# --------------------------------------------------------------------------------------------
# Licensed under the MIT License. See LICENSE in the repository root for license information.
# --------------------------------------------------------------------------------------------

from knack.help_files import helps  # pylint: disable=unused-import

helps['account refresh-token'] = """
type: command
short-summary: Get a new access token for the signed-in account, without signing in again.
long-summary: >
    Replaces exactly the token that `az account get-access-token` returns for the same arguments, by
    asking Microsoft Entra ID for a new one with the account's existing sign-in. Use it to pick up a
    group or role change, for example after activating a PIM for Groups assignment, in `az` and in
    every tool that gets its tokens from `az`.


    The command takes the same selection arguments as `az account get-access-token`, with the same
    values and the same defaults: with no arguments it refreshes the Azure Resource Manager token.
    It refreshes one token per run.


    A refresh counts only when it is proven: the token the Azure CLI returns afterwards must differ
    from the one it returned before, and must have been issued no earlier than 10 minutes before the
    command started (Microsoft Entra ID dates tokens a few minutes early, and clocks differ). If it
    cannot be proven, the command fails with a non-zero exit code.


    `status` is `issued` when the token the command started from was itself obtained during this
    run: its issue time is within the command's run time, plus a few seconds, of the new token's.
    That is typically the case when the Azure CLI had none cached for the request and got one for
    this run. Otherwise it is `refreshed`. In both cases a new token is requested and proven.


    The command never prints an access token or a refresh token; it shows a short fingerprint (the
    first 12 hexadecimal characters of the SHA-256 hash) of the old and the new token. It never
    prompts and never opens a browser: if the account must sign in again, it stops and names the
    `az login` command to run. Managed identity and Cloud Shell accounts are not supported.
examples:
    - name: Refresh the Azure Resource Manager token of the current account
      text: >
        az account refresh-token
    - name: Refresh the token used with the Microsoft Graph API
      text: >
        az account refresh-token --resource-type ms-graph
    - name: Refresh the token for a resource
      text: >
        az account refresh-token --resource https://vault.azure.net
    - name: Refresh the token for a scope
      text: >
        az account refresh-token --scope https://graph.microsoft.com/.default
    - name: Refresh the token for a specific tenant
      text: >
        az account refresh-token --tenant 00000000-0000-0000-0000-000000000000
    - name: Refresh the token for a specific subscription
      text: >
        az account refresh-token --subscription 00000000-0000-0000-0000-000000000000
    - name: Refresh the token and show the claims of the new token, for example to see a new group
      text: >
        az account refresh-token --show-claims
    - name: Print only the fingerprint of the new token
      text: >
        az account refresh-token --query fingerprint --output tsv
"""
