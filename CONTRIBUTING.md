# Contributing

Thank you for helping. This guide shows how to build, test and submit a change. You need Python and
the Azure CLI. You do not need an Azure account, a tenant or any secret: the tests run the real Azure
CLI against a small local stand-in for Microsoft Entra ID.

By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md). Report security
problems privately, as described in [SECURITY.md](SECURITY.md).

## Prerequisites

* Python 3.12 or later.
* The Azure CLI, version 2.71.0 or later, either on your `PATH` or installed in a virtual
  environment. In the second case point `AZ_PYTHON` at that environment's Python interpreter:

  ```bash
  python3.12 -m venv ../.venv-az
  ../.venv-az/bin/python -m pip install azure-cli
  export AZ_PYTHON=$PWD/../.venv-az/bin/python
  ```

  To test the minimum supported release, install Azure CLI 2.71.0 with the requirement file
  Microsoft publishes for it (`src/azure-cli/requirements.py3.<Linux|Darwin|windows>.txt` in the
  `azure-cli` repository at tag `azure-cli-2.71.0`) instead of the latest.

Keep virtual environments outside this repository.

## Run the tests

```bash
python -m venv ../.venv-test
../.venv-test/bin/python -m pip install -r requirements/test.txt -r requirements/build.txt

# Unit tests: no Azure CLI needed
../.venv-test/bin/python -m pytest tests/unit

# Integration tests: build the wheel, install it into a real Azure CLI, run against the fake
../.venv-test/bin/python -m pytest tests/integration
```

(On Windows the interpreter is `..\.venv-test\Scripts\python.exe`.)

The integration tests build the wheel themselves. To test a wheel you built, set `EXTENSION_WHEEL` to
its path. Build one with:

```bash
../.venv-test/bin/python -m build --wheel --no-isolation --outdir dist src/refresh-token
```

The wheel holds only the `azext_refresh_token` package.

The tests give every Azure CLI call a temporary configuration directory and a temporary home
directory, so your own Azure CLI sign-in is never read or changed. A test fails if a file called
`.azure` shows up in its temporary home.

`tests/fake_entra/` is the stand-in for Microsoft Entra ID. It is test tooling: it serves only the
part of the protocol the Azure CLI and MSAL use, it is not part of the wheel and it is not meant for
anyone to run by hand.

## Style and lint

The Azure CLI's extension tooling checks style and help text. Run it in its own virtual
environment, with a throwaway configuration directory:

```bash
python -m venv ../.venv-lint
../.venv-lint/bin/python -m pip install -r requirements/lint.txt
. ../.venv-lint/bin/activate
export AZURE_CONFIG_DIR=$(mktemp -d)
PIP_CONSTRAINT="$PWD/requirements/lint-azure-cli.txt" azdev setup --repo "$PWD" --ext refresh-token
azdev style refresh-token
azdev linter refresh-token
```

The lint runs against a fixed Azure CLI release, because `azdev setup` would otherwise install the
newest one; the constraints file sets it, and dependency updates bump it.

## Rules for changes

* **Never print or log a token.** Not an access token, not a refresh token, not at any log level. To
  compare tokens, compare their SHA-256 fingerprints. A test must prove that new output paths do not
  leak.
* **Public interfaces only.** The extension uses the Azure CLI's extension surface, the Azure SDK
  credential protocol, MSAL's public API and the public API of `pymsalruntime`. Do not import a name
  that starts with an underscore from them, and do not patch functions at runtime. The one exception
  is `from azure.cli.core._profile import Profile`: the class is public, and that module is the only
  place the Azure CLI publishes it. If a behaviour needs private code, document it as a limitation
  instead.
* **Few dependencies.** At runtime the extension uses only what the Azure CLI ships and the standard
  library. A new test or tooling dependency needs a reason in the pull request.
* **Pure core, thin shell.** Decisions live in `selection.py`, `proof.py` and `result.py`, which use
  only the standard library and touch no network, file or clock. `azure_cli.py` and `broker.py` stay
  thin. Add unit tests for decisions; use the integration tests for behaviour that needs the real
  Azure CLI.
* **Never assume.** If a change depends on how Microsoft Entra ID, the Azure CLI or an operating
  system broker behaves, test what you can against the fake, and say in the pull request what you
  could not check.
* Keep pinned test and tooling versions in `requirements/`; Dependabot proposes updates.

## Commits and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
`test:`, `ci:`, `chore:`, `refactor:`, `style:`, with `!` or a `BREAKING CHANGE:` footer for an
incompatible change.

Add an entry to `src/refresh-token/HISTORY.rst` for every user-visible change. The extension
follows semantic versioning (before 1.0.0, an incompatible change raises the minor version). Its
public contract is the extension name, the command and its parameters and defaults, the fields of
the JSON output, the exit codes and the minimum Azure CLI version.

One check, `ci-ok`, gates a merge. It passes only when style, lint, the wheel build, the release dry
run (which prepares the release files from the built wheel, as a release would) and the unit and
integration tests have passed on Linux, macOS and Windows with the minimum and the latest Azure CLI.
The same suite runs every Monday against the newest Azure CLI release.

## Releases

For maintainers. A release pull request sets `VERSION` in `src/refresh-token/setup.py` and adds the
matching heading, with its entries, to `src/refresh-token/HISTORY.rst`. After it is merged, a
maintainer pushes a signed, annotated tag on `main`:

```bash
git tag -s -m "azure-cli-refresh-token vX.Y.Z" vX.Y.Z
git push origin vX.Y.Z
```

The release workflow checks the tag (annotated, signature verified by GitHub, on `main`, matching
the version and a `HISTORY.rst` heading), builds the wheel, waits for approval in the `release`
environment, attests the wheel and publishes the GitHub Release with the wheel, its SHA-256 and the
notes. Just before publishing it checks the tag once more against the commit that was built, so a
tag that was deleted and pushed again while the release waited for approval stops the release. A
pushed tag is never moved: a broken release is fixed by the next version.

The workflow can also be run by hand. That is a dry run: it builds the wheel and prepares the
release files, and publishes nothing.
