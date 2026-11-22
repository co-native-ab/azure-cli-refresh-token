# Azure CLI extension: refresh-token

An [Azure CLI](https://learn.microsoft.com/cli/azure/) extension that refreshes
the access tokens the CLI has cached, without signing out and in again.

Access tokens carry your group memberships and roles at the time they were
issued. When those change, for example after activating a
[PIM for Groups](https://learn.microsoft.com/entra/id-governance/privileged-identity-management/concept-pim-for-groups)
assignment, the Azure CLI keeps using the cached token until it expires. This
extension asks Microsoft Entra ID for new tokens for the same signed-in account,
so the next `az` command, and tools that get their tokens from the Azure CLI,
see the change right away.

> **Status:** early development. Nothing is released yet, and the interface may
> change without notice.

## License

[MIT](LICENSE)
