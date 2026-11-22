"""Prepare and check a release of the refresh-token extension.

Two commands, used by the release workflow and, for ``prepare``, by every pull request:

    python tools/release.py prepare --dist <dir> --out <dir> [--tag <tag>]
    python tools/release.py verify-tag --repo <owner/name> --tag <tag> --sha <commit sha>

``prepare`` checks the version, the changelog and the wheel and writes the wheel, its SHA-256 line
and the release notes into ``--out``. It never contacts the network. ``verify-tag`` asks the GitHub
API whether a pushed tag is annotated, signed (as GitHub verifies it), points at the commit that
was checked out and is on ``main``.

This script never creates, moves or deletes a tag and never publishes anything. It uses only the
standard library and runs on Python 3.9 and later.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP_PY = ROOT / 'src' / 'refresh-token' / 'setup.py'
HISTORY = ROOT / 'src' / 'refresh-token' / 'HISTORY.rst'

ISSUES = 'https://github.com/co-native-ab/azure-cli-refresh-token/issues/'

NOTICE_HEADING = '## Windows and macOS broker: not verified yet'

# The README carries the same text; a unit test keeps the two equal.
BROKER_NOTICE = (
    '**The Windows and macOS broker path is not verified yet.** When the Azure CLI signs in\n'
    "through the operating system's broker (the default on Windows, and on macOS when you turn it\n"
    'on), the extension renews the token in the broker and then has the Azure CLI fetch it. That\n'
    'sequence is tested against a stand-in for the broker, but not yet on real Windows or macOS\n'
    'systems. It fails closed: if the new token cannot be proven, the command stops with an error\n'
    'and never reports an old token as new.\n'
    '\n'
    'Help us verify it: Windows in ' + ISSUES + '3,\n'
    'macOS in ' + ISSUES + '4.\n'
    'Please comment with your operating system and its version, the output of `az version`,\n'
    "whether the broker is on, the command's exit code and status, any error text, and these\n"
    'lines from `az account refresh-token --debug` (they also appear with `--verbose`):\n'
    '`New token <fingerprint>: same`, `stale`, `unreadable` or `proven`, and\n'
    '`Renewing the token in the broker for scopes [...]`. Fingerprints are safe to share. Never\n'
    'paste a token, and do not paste the full debug output.'
)


class ReleaseError(Exception):
    """A check failed; the message says what to fix."""


def read_version(text):
    match = re.search(r"^VERSION = '([^']+)'$", text, re.MULTILINE)
    if not match:
        raise ReleaseError('no VERSION = \'x.y.z\' line in src/refresh-token/setup.py')
    return match.group(1)


def check_tag(tag, version):
    if tag != 'v' + version:
        raise ReleaseError(
            "the tag is '{}', but setup.py has version {}; the tag must be 'v{}'".format(
                tag, version, version))


def _is_underline(line):
    return bool(line) and set(line) == {'+'}


def history_section(text, version):
    """Return the changelog text under the heading for the version."""
    lines = text.splitlines()
    start = None
    for index in range(len(lines) - 1):
        underline = lines[index + 1]
        if (lines[index] == version and _is_underline(underline)
                and len(underline) >= len(version)):
            start = index + 2
            break
    if start is None:
        raise ReleaseError(
            'HISTORY.rst has no heading for {} (the version, then a line of + at least as '
            'long)'.format(version))
    end = len(lines)
    for index in range(start, len(lines) - 1):
        if lines[index] and _is_underline(lines[index + 1]) and len(lines[index + 1]) >= len(lines[index]):
            end = index
            break
    section = '\n'.join(lines[start:end]).strip()
    if not section:
        raise ReleaseError('the HISTORY.rst section for {} is empty'.format(version))
    return section


_LIST_ITEM = re.compile(r'^\s*(?:[*+-]|\d+[.)])\s')


def unwrap(text):
    """Join hard-wrapped lines, so each paragraph and list item is one line.

    GitHub shows a single newline in a release body as a line break, so wrapped text would show
    broken lines. Blank lines, headings, list items and fenced code blocks keep their structure.
    """
    out = []
    joinable = False
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            out.append(line)
            joinable = False
        elif in_fence:
            out.append(line)
        elif not line.strip():
            out.append('')
            joinable = False
        elif line.lstrip().startswith('#'):
            out.append(line)
            joinable = False
        elif joinable and not _LIST_ITEM.match(line):
            out[-1] = out[-1].rstrip() + ' ' + line.strip()
        else:
            out.append(line.rstrip())
            joinable = True
    return '\n'.join(out)


def release_notes(section):
    """Markdown release notes: the changelog section, then the broker notice, one line per
    paragraph and list item."""
    body = re.sub(r'``([^`]+)``', r'`\1`', section)
    return unwrap('{}\n\n{}\n\n{}'.format(body, NOTICE_HEADING, BROKER_NOTICE)) + '\n'


def expected_wheel(version):
    return 'refresh_token-{}-py3-none-any.whl'.format(version)


def checksum_line(name, data):
    """A line in the format `sha256sum -c` reads."""
    return '{}  {}\n'.format(hashlib.sha256(data).hexdigest(), name)


def tag_problems(ref, tag_object, compare_status, sha):
    """Judge the three GitHub API answers about a tag; an empty list means the tag is good.

    ``ref`` is the tag's ref, ``tag_object`` the annotated tag object (None when the tag is not
    annotated), ``compare_status`` the status of comparing ``main`` with the tagged commit, and
    ``sha`` the commit that was checked out.
    """
    if ref['object']['type'] != 'tag':
        return ['the tag is not annotated; push a signed, annotated tag']
    problems = []
    verification = tag_object.get('verification')
    if not isinstance(verification, dict):
        verification = {}
    if not verification.get('verified'):
        problems.append("GitHub did not verify the tag's signature (reason: {})".format(
            verification.get('reason', 'unknown')))
    target = tag_object['object']
    if target['type'] != 'commit':
        problems.append('the tag does not point at a commit (it points at a {})'.format(
            target['type']))
    elif target['sha'] != sha:
        problems.append('the tag points at {}, but the workflow checked out {}'.format(
            target['sha'], sha))
    if compare_status not in ('identical', 'behind'):
        problems.append('the tagged commit is not on main (status: {})'.format(compare_status))
    return problems


def prepare(dist, out, tag=None):
    version = read_version(SETUP_PY.read_text(encoding='utf-8'))
    if tag is not None:
        check_tag(tag, version)
    section = history_section(HISTORY.read_text(encoding='utf-8'), version)
    name = expected_wheel(version)
    wheels = sorted(path.name for path in Path(dist).glob('*.whl'))
    if wheels != [name]:
        raise ReleaseError('{} must hold exactly one wheel, named {}; found: {}'.format(
            dist, name, ', '.join(wheels) or 'none'))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    wheel = out / name
    shutil.copyfile(Path(dist) / name, wheel)
    checksum = out / (name + '.sha256')
    checksum.write_text(checksum_line(name, wheel.read_bytes()), encoding='utf-8')
    notes = out / 'notes.md'
    notes.write_text(release_notes(section), encoding='utf-8')
    print('version {}'.format(version))
    for path in (wheel, checksum, notes):
        print(path)


def _gh_api(endpoint):
    result = subprocess.run(['gh', 'api', endpoint], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise ReleaseError('gh api {} failed: {}'.format(endpoint, result.stderr.strip()))
    return json.loads(result.stdout)


def _get(data, what, *keys):
    """Read a nested key from a GitHub answer; a missing or malformed field is a ReleaseError."""
    value = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ReleaseError('the GitHub answer for {} has no {}'.format(what, '.'.join(keys)))
        value = value[key]
    return value


def _object_id(value, what):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ReleaseError('the GitHub answer for {} has an unexpected object id'.format(what))
    return value


def verify_tag(repo, tag, sha):
    # A tag name that is not exactly v<VERSION> never reaches an API path.
    check_tag(tag, read_version(SETUP_PY.read_text(encoding='utf-8')))
    base = 'repos/{}'.format(repo)
    ref = _gh_api('{}/git/ref/tags/{}'.format(base, tag))
    if not isinstance(ref, dict) or ref.get('ref') != 'refs/tags/' + tag:
        raise ReleaseError('GitHub did not answer with the ref refs/tags/{}'.format(tag))
    if _get(ref, 'the tag ref', 'object', 'type') != 'tag':
        problems = tag_problems(ref, None, None, sha)
    else:
        tag_id = _object_id(_get(ref, 'the tag ref', 'object', 'sha'), 'the tag ref')
        tag_object = _gh_api('{}/git/tags/{}'.format(base, tag_id))
        _get(tag_object, 'the tag object', 'object', 'type')
        commit = _object_id(_get(tag_object, 'the tag object', 'object', 'sha'), 'the tag object')
        comparison = _gh_api('{}/compare/refs/heads/main...{}'.format(base, commit))
        status = _get(comparison, 'the comparison with main', 'status')
        problems = tag_problems(ref, tag_object, status, sha)
    if problems:
        raise ReleaseError('; '.join(problems))
    print('tag {} is annotated, verified and on main'.format(tag))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare', help='check and write the release files')
    prepare_parser.add_argument('--dist', required=True)
    prepare_parser.add_argument('--out', required=True)
    prepare_parser.add_argument('--tag')
    verify_parser = commands.add_parser('verify-tag', help='check a pushed tag through GitHub')
    verify_parser.add_argument('--repo', required=True)
    verify_parser.add_argument('--tag', required=True)
    verify_parser.add_argument('--sha', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            prepare(args.dist, args.out, args.tag)
        else:
            verify_tag(args.repo, args.tag, args.sha)
    except ReleaseError as error:
        print('error: {}'.format(error), file=sys.stderr)
        if os.environ.get('GITHUB_ACTIONS'):
            print('::error::{}'.format(error))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
