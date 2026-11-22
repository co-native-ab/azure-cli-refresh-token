import hashlib
from pathlib import Path

import pytest

import release
from release import ReleaseError

ROOT = Path(__file__).resolve().parents[2]
# The released version, read from the real setup script so a version bump does not break the tests.
VERSION = release.read_version(
    (ROOT / 'src' / 'refresh-token' / 'setup.py').read_text(encoding='utf-8'))
HISTORY_TEXT = (ROOT / 'src' / 'refresh-token' / 'HISTORY.rst').read_text(encoding='utf-8')
COMMIT = 'a' * 40
OTHER_COMMIT = 'b' * 40
TAG_OBJECT = 'c' * 40

HISTORY = """\
.. :changelog:

Release History
===============

0.2.0
+++++
* Newest change with ``code``.

0.1.1
+++++
* Middle change.

0.1.0
+++++
* First change.
* Mentions 0.2.0 only in its body.
"""


def good_ref():
    return {'object': {'type': 'tag', 'sha': TAG_OBJECT}}


def good_tag_object():
    return {
        'verification': {'verified': True, 'reason': 'valid'},
        'object': {'type': 'commit', 'sha': COMMIT},
    }


# read_version

def test_read_version_from_the_setup_script_text():
    assert release.read_version("from x import y\n\nVERSION = '1.2.3'\n") == '1.2.3'


def test_read_version_from_the_real_setup_script():
    text = (ROOT / 'src' / 'refresh-token' / 'setup.py').read_text(encoding='utf-8')
    assert release.read_version(text).count('.') == 2


def test_read_version_missing_is_an_error():
    with pytest.raises(ReleaseError, match='VERSION'):
        release.read_version('setup()\n')


# check_tag

def test_check_tag_accepts_the_matching_tag():
    release.check_tag('v0.1.0', '0.1.0')


@pytest.mark.parametrize('tag', ['0.1.0', 'v0.1.1', 'v0.1.0-rc1'])
def test_check_tag_names_both_when_they_differ(tag):
    with pytest.raises(ReleaseError) as raised:
        release.check_tag(tag, '0.1.0')
    assert tag in str(raised.value)
    assert 'v0.1.0' in str(raised.value)


# history_section

def test_history_section_picks_the_right_section():
    section = release.history_section(HISTORY, '0.1.1')
    assert section == '* Middle change.'


def test_history_section_stops_at_the_next_heading():
    section = release.history_section(HISTORY, '0.2.0')
    assert section == '* Newest change with ``code``.'


def test_history_section_last_section_runs_to_the_end_of_the_file():
    section = release.history_section(HISTORY, '0.1.0')
    assert section == '* First change.\n* Mentions 0.2.0 only in its body.'


def test_history_section_version_only_in_the_body_is_an_error():
    text = 'Release History\n===============\n\n0.1.0\n+++++\n* Mentions 0.3.0 here.\n'
    with pytest.raises(ReleaseError, match='0.3.0'):
        release.history_section(text, '0.3.0')


def test_history_section_short_underline_is_not_a_heading():
    text = '0.1.0\n++++\n* Not a section.\n'
    with pytest.raises(ReleaseError, match='0.1.0'):
        release.history_section(text, '0.1.0')


def test_history_section_empty_section_is_an_error():
    text = '0.1.0\n+++++\n\n0.0.9\n+++++\n* Older.\n'
    with pytest.raises(ReleaseError, match='empty'):
        release.history_section(text, '0.1.0')


# release_notes

def test_release_notes_order_and_code_spans():
    notes = release.release_notes('* A ``literal`` here.')
    assert notes == (
        '* A `literal` here.\n\n'
        '## Windows and macOS broker: not verified yet\n\n'
        + release.unwrap(release.BROKER_NOTICE) + '\n'
    )


def _paragraphs_outside_fences(notes):
    blocks, current, in_fence = [], [], False
    for line in notes.splitlines():
        if line.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def test_release_notes_have_no_line_breaks_inside_a_paragraph():
    # GitHub shows a single newline in a release body as a line break.
    section = release.history_section(HISTORY_TEXT, VERSION)
    notes = release.release_notes(section)
    for block in _paragraphs_outside_fences(notes):
        if len(block) > 1:
            assert all(line.startswith('* ') for line in block), block


def test_unwrap_joins_paragraphs_and_list_items_and_keeps_code_fences():
    text = (
        'A paragraph\nwrapped here.\n\n'
        '* item one\n  continued\n* item two\n\n'
        '## Heading\n\n'
        '```bash\nline one\nline two\n```\n'
        'after'
    )
    assert release.unwrap(text) == (
        'A paragraph wrapped here.\n\n'
        '* item one continued\n* item two\n\n'
        '## Heading\n\n'
        '```bash\nline one\nline two\n```\n'
        'after'
    )


def test_notice_unwrapped_is_one_line_per_paragraph():
    paragraphs = release.unwrap(release.BROKER_NOTICE).split('\n\n')
    assert len(paragraphs) == 2
    assert all('\n' not in p for p in paragraphs)


def test_release_notes_double_backticks_become_code_spans():
    assert release.release_notes('``x``').startswith('`x`\n')


def test_notice_points_at_the_verification_issues():
    base = 'https://github.com/co-native-ab/azure-cli-refresh-token/issues/'
    assert 'Windows in ' + base + '3' in release.BROKER_NOTICE
    assert 'macOS in ' + base + '4' in release.BROKER_NOTICE


# expected_wheel / checksum_line

def test_expected_wheel_name():
    assert release.expected_wheel('0.1.0') == 'refresh_token-0.1.0-py3-none-any.whl'


def test_checksum_line_is_in_sha256sum_format():
    assert release.checksum_line('w.whl', b'abc') == (
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  w.whl\n')


# tag_problems

def test_good_tag_has_no_problems():
    assert release.tag_problems(good_ref(), good_tag_object(), 'behind', COMMIT) == []


def test_good_tag_on_main_itself_has_no_problems():
    assert release.tag_problems(good_ref(), good_tag_object(), 'identical', COMMIT) == []


def test_lightweight_tag_is_not_annotated():
    ref = {'object': {'type': 'commit', 'sha': COMMIT}}
    (problem,) = release.tag_problems(ref, None, None, COMMIT)
    assert 'not annotated' in problem


def test_unverified_signature_shows_the_reason():
    tag_object = good_tag_object()
    tag_object['verification'] = {'verified': False, 'reason': 'unsigned'}
    (problem,) = release.tag_problems(good_ref(), tag_object, 'behind', COMMIT)
    assert 'signature' in problem
    assert 'unsigned' in problem


def test_tag_object_on_a_tree_does_not_point_at_a_commit():
    tag_object = good_tag_object()
    tag_object['object']['type'] = 'tree'
    problems = release.tag_problems(good_ref(), tag_object, 'behind', COMMIT)
    assert any('does not point at a commit' in p for p in problems)


def test_commit_that_differs_from_the_checked_out_commit():
    problems = release.tag_problems(good_ref(), good_tag_object(), 'behind', OTHER_COMMIT)
    (problem,) = problems
    assert COMMIT in problem
    assert OTHER_COMMIT in problem


@pytest.mark.parametrize('status', ['ahead', 'diverged'])
def test_commit_not_on_main(status):
    (problem,) = release.tag_problems(good_ref(), good_tag_object(), status, COMMIT)
    assert 'not on main' in problem
    assert status in problem


# verify_tag

def fake_api(monkeypatch, answers):
    """Answer `gh api` calls from a dict keyed by endpoint suffix; record the endpoints asked."""
    asked = []

    def api(endpoint):
        asked.append(endpoint)
        for suffix, answer in answers.items():
            if endpoint.endswith(suffix):
                return answer
        raise AssertionError('unexpected endpoint ' + endpoint)

    monkeypatch.setattr(release, '_gh_api', api)
    return asked


def good_answers():
    return {
        '/git/ref/tags/v' + VERSION: dict(good_ref(), ref='refs/tags/v' + VERSION),
        '/git/tags/' + TAG_OBJECT: good_tag_object(),
        '...' + COMMIT: {'status': 'behind'},
    }


def test_verify_tag_accepts_a_good_tag_and_compares_against_the_main_branch_ref(
        monkeypatch, capsys):
    asked = fake_api(monkeypatch, good_answers())
    release.verify_tag('o/r', 'v' + VERSION, COMMIT)
    assert 'repos/o/r/compare/refs/heads/main...' + COMMIT in asked
    assert 'is annotated, verified and on main' in capsys.readouterr().out


def test_verify_tag_rejects_another_tag_name_before_any_api_call(monkeypatch):
    asked = fake_api(monkeypatch, {})
    with pytest.raises(ReleaseError, match='must be'):
        release.verify_tag('o/r', 'v' + VERSION + '.1', COMMIT)
    assert asked == []


def test_verify_tag_list_answer_is_an_error_not_a_traceback(monkeypatch):
    answers = good_answers()
    answers['/git/ref/tags/v' + VERSION] = [{'ref': 'refs/tags/v' + VERSION + '.1'}]
    fake_api(monkeypatch, answers)
    with pytest.raises(ReleaseError, match='did not answer with the ref'):
        release.verify_tag('o/r', 'v' + VERSION, COMMIT)


def test_verify_tag_answer_for_another_ref_is_an_error(monkeypatch):
    answers = good_answers()
    answers['/git/ref/tags/v' + VERSION]['ref'] = 'refs/tags/v9.9.9'
    fake_api(monkeypatch, answers)
    with pytest.raises(ReleaseError, match='did not answer with the ref'):
        release.verify_tag('o/r', 'v' + VERSION, COMMIT)


@pytest.mark.parametrize('key', ['/git/ref/tags/v' + VERSION, '/git/tags/' + TAG_OBJECT])
def test_verify_tag_missing_object_is_an_error(monkeypatch, key):
    answers = good_answers()
    del answers[key]['object']
    fake_api(monkeypatch, answers)
    with pytest.raises(ReleaseError, match='has no object'):
        release.verify_tag('o/r', 'v' + VERSION, COMMIT)


def test_verify_tag_missing_comparison_status_is_an_error(monkeypatch):
    answers = good_answers()
    answers['...' + COMMIT] = {}
    fake_api(monkeypatch, answers)
    with pytest.raises(ReleaseError, match='has no status'):
        release.verify_tag('o/r', 'v' + VERSION, COMMIT)


def test_verify_tag_odd_object_id_never_reaches_an_api_path(monkeypatch):
    answers = good_answers()
    answers['/git/ref/tags/v' + VERSION]['object']['sha'] = '../x'
    asked = fake_api(monkeypatch, answers)
    with pytest.raises(ReleaseError, match='object id'):
        release.verify_tag('o/r', 'v' + VERSION, COMMIT)
    assert len(asked) == 1


# prepare

def dummy_wheel(directory, name=None, data=b'wheel bytes'):
    name = name or release.expected_wheel(VERSION)
    directory.mkdir(exist_ok=True)
    (directory / name).write_bytes(data)
    return directory / name


def test_prepare_writes_the_three_outputs(tmp_path, capsys):
    wheel = dummy_wheel(tmp_path / 'dist')
    out = tmp_path / 'out'
    assert release.main(['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        'notes.md', wheel.name, wheel.name + '.sha256']
    assert (out / wheel.name).read_bytes() == wheel.read_bytes()
    digest, name = (out / (wheel.name + '.sha256')).read_text().rstrip('\n').split('  ')
    assert name == wheel.name
    assert digest == hashlib.sha256(wheel.read_bytes()).hexdigest()
    notes = (out / 'notes.md').read_text(encoding='utf-8')
    assert 'Windows and macOS broker: not verified yet' in notes
    assert release.unwrap(release.BROKER_NOTICE) in notes
    assert wheel.name in capsys.readouterr().out


def test_prepare_accepts_the_matching_tag(tmp_path):
    dummy_wheel(tmp_path / 'dist')
    args = ['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(tmp_path / 'out')]
    assert release.main(args + ['--tag', 'v' + VERSION]) == 0


def test_prepare_rejects_another_tag(tmp_path, capsys):
    dummy_wheel(tmp_path / 'dist')
    args = ['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(tmp_path / 'out')]
    assert release.main(args + ['--tag', 'v' + VERSION + '.1']) == 1
    assert 'error: ' in capsys.readouterr().err


def test_prepare_without_a_wheel_names_the_expected_file(tmp_path, capsys):
    (tmp_path / 'dist').mkdir()
    args = ['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(tmp_path / 'out')]
    assert release.main(args) == 1
    assert release.expected_wheel(VERSION) in capsys.readouterr().err


def test_prepare_with_two_wheels_is_an_error(tmp_path, capsys):
    dummy_wheel(tmp_path / 'dist')
    dummy_wheel(tmp_path / 'dist', name=release.expected_wheel('0.0.9'))
    args = ['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(tmp_path / 'out')]
    assert release.main(args) == 1
    assert release.expected_wheel(VERSION) in capsys.readouterr().err


def test_prepare_with_a_wrongly_named_wheel_is_an_error(tmp_path, capsys):
    dummy_wheel(tmp_path / 'dist', name=release.expected_wheel('0.0.9'))
    args = ['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(tmp_path / 'out')]
    assert release.main(args) == 1
    assert release.expected_wheel(VERSION) in capsys.readouterr().err


def test_errors_become_github_annotations_on_actions(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    (tmp_path / 'dist').mkdir()
    args = ['prepare', '--dist', str(tmp_path / 'dist'), '--out', str(tmp_path / 'out')]
    assert release.main(args) == 1
    assert '::error::' in capsys.readouterr().out
