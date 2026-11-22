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

> **Status:** first release, 0.1.0. Before 1.0.0 an incompatible change can still come in a minor
> release; [HISTORY.rst](src/refresh-token/HISTORY.rst) says what changed.

## Install

```bash
az extension add --source https://github.com/co-native-ab/azure-cli-refresh-token/releases/download/v0.1.0/refresh_token-0.1.0-py3-none-any.whl
```

The Azure CLI asks you to confirm an extension from a source it cannot verify. Answer `y`, or add
`--yes`.

To verify the wheel first, download it from the release, check its SHA-256 hash and its build
provenance, and install the file you checked:

```bash
gh release download v0.1.0 --repo co-native-ab/azure-cli-refresh-token
sha256sum -c refresh_token-0.1.0-py3-none-any.whl.sha256    # macOS: shasum -a 256 -c ...
gh attestation verify refresh_token-0.1.0-py3-none-any.whl --repo co-native-ab/azure-cli-refresh-token
az extension add --source ./refresh_token-0.1.0-py3-none-any.whl
```

The extension needs Azure CLI 2.71.0 or later. It adds one command, `az account refresh-token`, and
depends on nothing but what the Azure CLI already ships. To build it from source instead, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Usage

```bash
# Refresh the Azure Resource Manager token, the one `az account get-access-token` returns
az account refresh-token

# Refresh the token for another audience
az account refresh-token --resource-type ms-graph
az account refresh-token --resource https://vault.azure.net
az account refresh-token --scope https://graph.microsoft.com/.default

# Refresh the token for a tenant or a subscription
az account refresh-token --tenant 00000000-0000-0000-0000-000000000000
az account refresh-token --subscription 00000000-0000-0000-0000-000000000000

# See the claims of the new token, for example to check that a new group arrived
az account refresh-token --show-claims

# Only the fingerprint
az account refresh-token --query fingerprint --output tsv
```

`az account refresh-token` takes the selection arguments of `az account get-access-token`
(`--resource-type`, `--resource`, `--scope`, `--tenant`, `--subscription`) with the same values,
validation and defaults, and replaces exactly the token that command returns for the same
arguments. It refreshes one token per run and never changes anything else: it does not remove
accounts, sign you out or change the Azure CLI configuration.

### Output

The command prints one JSON object. `--output` and `--query` work as for any Azure CLI command.

| Field | Meaning |
| --- | --- |
| `status` | `refreshed`, or `issued` (see below) |
| `scopes` | The scopes the token was requested for |
| `audience` | The audience (`aud`) of the new token |
| `tenant` | The tenant the token is for |
| `subscription` | The subscription used. Present only when `--tenant` is not given, as for `get-access-token` |
| `previousFingerprint`, `fingerprint` | The first 12 hexadecimal characters of the SHA-256 hash of the token the command started from and of the new token |
| `issuedAt` | When the new token was issued, from its `iat` claim, ISO 8601 in UTC. Microsoft Entra ID sets this time about 5 minutes before it actually issues the token, so it is usually about 5 minutes before the command ran |
| `expiresOn` | When the new token expires, ISO 8601 in UTC (unlike the local-time `expiresOn` of `get-access-token`) |
| `expires_on` | When the new token expires, as a POSIX timestamp, the same value `get-access-token` reports |
| `claims` | With `--show-claims` only: the decoded payload of the new token |

The command never prints, logs or stores an access token or a refresh token, not even with
`--debug`; a token is identified only by its fingerprint. `--show-claims` prints the payload of the
new token (never its header or signature), which contains personal data, so it is off by default.

`status` is `issued` when the token the command started from was itself obtained during this run:
its issue time is within the command's run time, plus a few seconds, of the new token's. That is
typically the case when nothing was cached for that audience and the Azure CLI had to get one first.
Otherwise it is `refreshed`. A new token is requested and checked in both cases.

### How a refresh is proven

The command succeeds only when the token the Azure CLI returns afterwards differs from the one it
returned before, and was issued no earlier than **600 seconds (10 minutes)** before the command
started. Otherwise it fails with a non-zero exit code and says that the token was not renewed.

Microsoft Entra ID dates a token a few minutes before it issues it, and the clock of this machine may
differ from the service's, so the check allows 10 minutes. An old token cannot pass because of that
allowance: it must also differ from the token the command started from. If the proof fails because
the local clock is far off, the error says so.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | A new token was obtained and proven |
| 1 | Any failure: not signed in, the sign-in must be renewed, an unsupported account, an unproven token, a network or service error |
| 2 | An argument the parser rejected, such as an unknown `--resource-type` |

The command never opens a browser, never starts a device-code flow and never waits for input. When
Microsoft Entra ID needs you to sign in again (an expired session, a multi-factor step-up or a
Conditional Access requirement), the command stops and prints the `az login` command to run.

## Windows and macOS broker: not verified yet

**The Windows and macOS broker path is not verified yet.** When the Azure CLI signs in
through the operating system's broker (the default on Windows, and on macOS when you turn it
on), the extension renews the token in the broker and then has the Azure CLI fetch it. That
sequence is tested against a stand-in for the broker, but not yet on real Windows or macOS
systems. It fails closed: if the new token cannot be proven, the command stops with an error
and never reports an old token as new.

Help us verify it: Windows in https://github.com/co-native-ab/azure-cli-refresh-token/issues/3,
macOS in https://github.com/co-native-ab/azure-cli-refresh-token/issues/4.
Please comment with your operating system and its version, the output of `az version`,
whether the broker is on, the command's exit code and status, any error text, and these
lines from `az account refresh-token --debug` (they also appear with `--verbose`):
`New token <fingerprint>: same`, `stale`, `unreadable` or `proven`, and
`Renewing the token in the broker for scopes [...]`. Fingerprints are safe to share. Never
paste a token, and do not paste the full debug output.

If a refresh cannot be proven while the broker is in use, the error names the Azure CLI setting that
turns the broker off (`core.enable_broker_on_windows` or `core.enable_broker_on_mac`). The extension
never changes it.

## Limitations

* Managed identity and Cloud Shell accounts are rejected before anything is requested. The Azure CLI
  gives no way to force a new token for them.
* The Windows and macOS broker path is not verified yet; see [the section above](#windows-and-macos-broker-not-verified-yet).
* Some Azure CLI versions add extra claims to broker requests in certain environments. The broker
  renewal then targets a different cache entry than the one the Azure CLI reads, the new token is
  not found, and the command fails closed instead of reporting a refresh it could not prove.
* When Microsoft Entra ID needs a user to sign in again, the Azure CLI itself may print a hint
  first (it recommends `az logout` and `az login ... --claims-challenge`). The extension cannot
  suppress it through public interfaces. Follow the command the extension prints after it: you do
  not need to sign out.
* A token without a readable issue time (an opaque, non-JWT token, which some personal Microsoft
  accounts receive for some audiences) cannot be proven, so the command fails for it.
* Azure CLI 2.71.0 to 2.75.x print a warning about a claims challenge on every refresh. That is
  expected.
* Microsoft Entra ID leaves the `groups` claim out of a token for users in very many groups. A token
  without it still counts as renewed; it just does not show the groups.
* The minimum is Azure CLI 2.71.0 because earlier releases do not pass a claims challenge on
  through the public credential for every account type. See [docs/design.md](docs/design.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a vulnerability, see [SECURITY.md](SECURITY.md).
How the extension works and why is written down in [docs/design.md](docs/design.md).

## License

[MIT](LICENSE)
