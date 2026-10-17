"""A subagent stop is a pause of a child session that names its parent."""

import io
import json
import pathlib
import shutil

import pytest
from agent_memory.adapters import capture as capture_module
from agent_memory.adapters import hook_entry, moments
from agent_memory.core import sessions
from agent_memory.core.config import EXECUTOR_ENV_VAR
from agent_memory.core.errors import ValidationError

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "claude"
PARENT = "parent-session"
AGENT = "a1b2c3"
AGENT_TYPE = "general-purpose"
WORK = "stale token cookie"


@pytest.fixture
def transcripts(tmp_path):
    target = tmp_path / "projects"
    shutil.copytree(FIXTURES, target)
    return target


def _event(transcripts, **overrides):
    event = {
        "hook_event_name": "SubagentStop",
        "session_id": PARENT,
        "transcript_path": str(transcripts / f"{PARENT}.jsonl"),
        "agent_id": AGENT,
        "agent_type": AGENT_TYPE,
        "agent_transcript_path": str(transcripts / PARENT / "subagents" / f"agent-{AGENT}.jsonl"),
        "last_assistant_message": "",
    }
    event.update(overrides)
    return event


def _launches():
    calls = []

    def launch(store, session, host):
        calls.append((session, host))
        return True

    return calls, launch


def _archived(store, session):
    return [message.text for message in sessions.read(store.layout, session)]


def test_subagent_stop_is_a_pause_in_the_claude_code_dialect():
    assert moments.moment_for(moments.HOST_CLAUDE_CODE, "SubagentStop") == moments.MOMENT_PAUSE


def test_subagent_work_is_archived_as_a_child_session_naming_its_parent(store, transcripts):
    calls, launch = _launches()

    response = hook_entry.handle(store, _event(transcripts), launch=launch)

    child = response["session"]
    assert PARENT in child and AGENT in child and child != PARENT
    archived = _archived(store, child)
    assert PARENT in archived[0] and AGENT_TYPE in archived[0]
    assert any(WORK in text for text in archived)
    assert not sessions.session_path(store.layout, PARENT).exists()
    assert calls == [(child, moments.HOST_CLAUDE_CODE)]


def test_a_repeated_subagent_stop_archives_only_new_work(store, transcripts):
    _, launch = _launches()
    first = hook_entry.handle(store, _event(transcripts), launch=launch)

    again = hook_entry.handle(store, _event(transcripts), launch=launch)

    assert again == {}
    assert len(_archived(store, first["session"])) == first["pending"]


def test_the_child_transcript_is_derived_when_the_host_omits_its_path(store, transcripts):
    _, launch = _launches()

    response = hook_entry.handle(
        store, _event(transcripts, agent_transcript_path=""), launch=launch
    )

    assert any(WORK in text for text in _archived(store, response["session"]))


def test_a_final_answer_missing_from_the_lagging_transcript_is_kept(store, transcripts):
    _, launch = _launches()
    final = "Handback: login loop fixed and covered by a regression test."

    response = hook_entry.handle(
        store, _event(transcripts, last_assistant_message=final), launch=launch
    )

    assert any(final in text for text in _archived(store, response["session"]))


def test_subagents_of_the_executor_session_stay_inert(store, transcripts, monkeypatch):
    monkeypatch.setenv(EXECUTOR_ENV_VAR, "1")
    event = {**_event(transcripts), "store": str(store.root)}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))

    assert hook_entry.main([]) == hook_entry.EXIT_OK
    assert not store.layout.sessions.exists() or not any(store.layout.sessions.iterdir())


@pytest.mark.redteam
@pytest.mark.parametrize("agent_id", ["../../escape", "a/b", "x#y"])
def test_a_hostile_agent_id_is_refused_before_anything_is_written(store, transcripts, agent_id):
    _, launch = _launches()

    with pytest.raises(ValidationError):
        hook_entry.handle(store, _event(transcripts, agent_id=agent_id), launch=launch)

    assert not store.layout.sessions.exists() or not any(store.layout.sessions.iterdir())
    assert not any(path.name.startswith("escape") for path in store.root.parent.rglob("*"))


@pytest.mark.redteam
def test_a_hostile_session_cannot_place_a_watermark_outside_the_store(store):
    store.config.write.session_archive_enabled = False

    with pytest.raises(ValidationError):
        capture_module.capture(store, "../../escape", ["user: hello"])

    assert not any(path.name.startswith("escape") for path in store.root.parent.rglob("*"))
