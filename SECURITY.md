# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability reporting on this
repository (the **Report a vulnerability** button on the Security tab). Do not open a public issue
or pull request for a vulnerability.

We will acknowledge a report as soon as we can and keep you informed until it is fixed.

## What counts

This extension handles credentials on the user's behalf, so anything that exposes or weakens them is
in scope, for example:

* any path that prints, logs or stores an access token or a refresh token, at any log level;
* any way to make the command refresh tokens it was not asked to refresh;
* any way to make it report success for a token that was not renewed;
* any way to make it sign in interactively, open a browser or change the Azure CLI's configuration or
  token cache.

Vulnerabilities in the Azure CLI, MSAL or Microsoft Entra ID itself belong to their owners; report
those to Microsoft.

## Supported versions

Only the latest release receives fixes.
