"""``az account refresh-token --help`` documents the command."""

import pytest

pytestmark = pytest.mark.integration


def test_help_documents_command(az):
    result = az.run('account', 'refresh-token', '--help')
    assert result.returncode == 0, result.stderr
    text = ' '.join(result.stdout.split())

    for expected in (
            'Get a new access token for the signed-in account',
            'refreshed', 'issued', '10 minutes',
            'never prints an access token', 'never prompts',
            '--resource-type', '--resource', '--scope', '--tenant', '--subscription',
            '--show-claims',
            'az account refresh-token --resource-type ms-graph',
            'az account refresh-token --resource https://',
            'az account refresh-token --scope',
            'az account refresh-token --tenant',
            'az account refresh-token --subscription',
            'az account refresh-token --show-claims',
            'az account refresh-token --query fingerprint --output tsv'):
        assert expected in text, expected
