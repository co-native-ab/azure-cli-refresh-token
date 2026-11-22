# refresh-token

An Azure CLI extension that adds `az account refresh-token`. It asks Microsoft Entra ID for a new
access token for the account the Azure CLI is already signed in with, without signing out and in
again, so that a group or role change shows up right away.

The new token replaces the cached one that `az account get-access-token` returns for the same
arguments, so the next `az` command, and every tool that gets its tokens from the Azure CLI, uses
it. The command never prints a token. See the repository README for usage and limitations.
