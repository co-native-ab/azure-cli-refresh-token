# Design

This note explains how `az account refresh-token` works and why it is built the way it is. It is
written for contributors; for usage see the [README](../README.md).

## What the command does

Given the arguments of `az account get-access-token`, the command:

1. records the start time and checks the arguments the same way `get-access-token` does;
2. looks up the signed-in account and refuses account types it cannot refresh (managed identity,
   Cloud Shell) before it asks Microsoft Entra ID for anything;
3. reads the token `get-access-token` returns now, the *starting token* (if nothing is cached, the
   Azure CLI gets one from Microsoft Entra ID during this run, which is why the command can report
   `issued`);
4. asks the Azure CLI's own credential for a new token with an empty claims challenge, which makes
   MSAL skip the access token it has cached, get a new one and store it where later
   `get-access-token` calls find it;
5. reads the token `get-access-token` returns again and proves it is new (see below);
6. prints fingerprints and times, and, with `--show-claims`, the payload of the new token.

Nothing is cached, signed out or configured by the extension itself. The only write to the token
cache is the one MSAL makes when the credential receives a new token. The extension never opens the
cache, its files or the broker's store.

## Same selection as `get-access-token`

The command declares the same parameters with the same values, validation and defaults, so a user
who knows what an argument refreshes already knows what it does here: the token `get-access-token`
would hand them. It asks the Azure CLI for the token with the same call `get-access-token` makes, so
the precedence (`--scope` over `--resource` over `--resource-type` over the Azure Resource Manager
default) and every run-time validation are the Azure CLI's own.

The list of `--resource-type` values and the cloud endpoint each one maps to is copied into
`selection.py`, because the Azure CLI keeps it in a command module that is not published for use by
others. An integration test compares the copy with the installed Azure CLI on every run, and the
weekly scheduled run catches a value added by a new release.

For a `--tenant` other than the account's own tenant the public credential has no tenant parameter.
The extension then uses the Azure CLI's auxiliary credential for that tenant, which passes the same
empty claims challenge on to MSAL.

## The minimum Azure CLI version is 2.71.0

Forcing a new token goes through the credential's `get_token(..., claims=...)`. Azure CLI releases
differ in what they do with `claims`:

* 2.45 to 2.66 pass it to MSAL for user accounts only; service principals silently get their cached
  token back.
* 2.67 to 2.70 drop it for every account type, so a forced refresh would return the cached token.
* 2.71.0 and later pass it to MSAL as a claims challenge for user and service principal accounts.

2.71.0 is therefore the first release where the public credential can force a new token for every
supported account type. Raising the minimum is an incompatible change.

## Why the empty claims challenge works

MSAL does not serve a cached access token when a claims challenge is present, and the Azure CLI
declares the `CP1` client capability, which MSAL merges into every request. An empty challenge
therefore sends Microsoft Entra ID the same request an ordinary refresh does; the only difference is
that the cached token is bypassed. The returned token is an ordinary token.

## The proof and its allowance

A refresh counts only when the token now in use differs from the starting token (compared by
SHA-256 fingerprint) and its `iat` claim is no earlier than the start time minus **600 seconds**.
The decision lives in `proof.py` and is pure: times are passed in.

The allowance exists because Microsoft Entra ID sets a token's issue time a few minutes before it
issues the token, and because the clock of this machine and the service's differ. A larger
allowance cannot let an old token through, since the token must also differ from the starting token.
A token whose issue time cannot be read cannot be proven, so the command fails rather than trust it.

The `issued` or `refreshed` label is decided after the proof, in `proof.label`, from the `iat` of
the starting token and of the new token and from the command's measured run time (a monotonic clock,
read in `custom.py`). It is `issued` when the two issue times differ by no more than the run time
plus 5 seconds, which holds whenever the starting token was obtained during this run (and for a
token cached only seconds before it). Both times come from the identity provider and carry the same
early dating, so that dating cancels out and the clock of this machine plays no part. The 5 seconds
cover the whole-second resolution of `iat` and small differences between the servers that issued the
two tokens. If either issue time cannot be read the label is `refreshed`. The label never influences
whether a new token is requested or proven, and the cache is never read to decide it: a new token is
always forced.

## The broker sequence

On Windows, and on macOS with the broker enabled, the Azure CLI signs users in through an operating
system broker. MSAL serves a plain `az` call from its own access-token cache before it asks the
broker, and stores whatever the broker returns in that cache. The empty claims challenge produces
the same request to the broker as an ordinary call, and the broker answers from its own cache, so
the forced call alone can return the old token.

When the proof fails and the broker may be in use, the extension therefore:

1. renews the token in the broker through the public `pymsalruntime` API: it finds the broker's
   account for the signed-in user name and silently acquires a token with
   `set_access_token_to_renew` set to the token the forced request returned (the starting token
   when the Azure CLI handed it back unchanged, otherwise the older token it returned instead), for
   the authority of that token's tenant, the same scopes and the same claims. A token without a
   readable tenant id is not renewed and the command fails;
2. repeats the credential call once, which makes MSAL fetch the renewed token from the broker and
   store it where plain `az` finds it;
3. proves the result again. If it still fails, the error names the Azure CLI setting that turns the
   broker off and leaves it unchanged.

Only silent calls are used; the extension never shows a broker window. The sequence lives in
`refresh.py`, which takes the Azure CLI and broker calls as functions, so every branch (which token
is renewed, at most one renewal, no renewal without a broker, a missing `pymsalruntime`, a broker
that needs a new sign-in) is unit tested without either. It has not been verified against a real
broker yet; see the limitations in the README.

## Public interfaces only

The extension uses the Azure CLI's extension surface, the Azure SDK credential protocol, MSAL's
public API and the public API of `pymsalruntime`. It imports no name that starts with an underscore
and replaces nothing at runtime; a unit test scans the source for both. `Profile` is the one import
from an underscore-prefixed module, `azure.cli.core._profile`: the class and the methods used
(`get_subscription`, `get_raw_token`, `get_login_credentials`) are public, that module is the only
place the Azure CLI publishes it, and Microsoft's own extensions import it from there.

## Pure core, thin shell

`selection.py`, `proof.py` and `result.py` take plain values and return plain values; they use only
the standard library. `azure_cli.py` and `broker.py` are the thin layer around the Azure CLI and the
broker library, `refresh.py` runs the refresh sequence on top of functions it is given, and
`custom.py` wires the real ones in. Tokens exist only as local variables in the
thin layer and `custom.py`; the core receives them only to hash them or decode their payload.

## The fake identity provider

The integration tests need a Microsoft Entra ID that a test can control: change a user's groups
between two requests, answer "interaction required", return the same token twice. `tests/fake_entra`
is a small HTTPS server, started by the tests, with a certificate authority created for each run.
The Azure CLI trusts it through `REQUESTS_CA_BUNDLE` and uses it as a custom cloud, and users sign in
with the device-code flow, which the fake approves at the first poll.

It implements only what the Azure CLI and MSAL use: OpenID discovery, the device-code and token
endpoints (device-code, refresh-token and client-credentials grants), the cloud metadata document
and the subscription list. It is a simplified model of the real service, so a passing test shows
agreement with the model; behaviour of the real service and of the brokers is not mocked, and is
listed as a limitation where it matters. The fake is never packaged in the wheel.
