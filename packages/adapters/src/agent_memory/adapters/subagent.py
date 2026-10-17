"""A subagent boundary: the child transcript becomes its own session that names its parent."""

from __future__ import annotations

import pathlib

from . import transcript

KEY_AGENT_ID = "agent_id"
KEY_AGENT_TYPE = "agent_type"
KEY_AGENT_TRANSCRIPT = "agent_transcript_path"
KEY_PARENT_TRANSCRIPT = "transcript_path"
KEY_FINAL = "last_assistant_message"
CHILD_MARKER = ".agent-"
SUBAGENTS_DIRNAME = "subagents"
TRANSCRIPT_PREFIX = "agent-"
TRANSCRIPT_SUFFIX = ".jsonl"
UNKNOWN_TYPE = "unknown"


def is_child(event: dict[str, object]) -> bool:
    return bool(event.get(KEY_AGENT_ID))


def child_session(parent: str, event: dict[str, object]) -> str:
    return f"{parent}{CHILD_MARKER}{event[KEY_AGENT_ID]}"


def items(parent: str, event: dict[str, object], host: str) -> list[str]:
    agent_type = str(event.get(KEY_AGENT_TYPE) or UNKNOWN_TYPE)
    header = f"system: subagent {agent_type} of session {parent}"
    found = with_final_answer(transcript.items(transcript_path(event), host=host), event)
    return [header, *found] if found else []


def transcript_path(event: dict[str, object]) -> pathlib.Path:
    supplied = str(event.get(KEY_AGENT_TRANSCRIPT) or "")
    if supplied:
        return pathlib.Path(supplied)
    parent = pathlib.Path(str(event.get(KEY_PARENT_TRANSCRIPT) or ""))
    name = f"{TRANSCRIPT_PREFIX}{event[KEY_AGENT_ID]}{TRANSCRIPT_SUFFIX}"
    return parent.with_suffix("") / SUBAGENTS_DIRNAME / name


def with_final_answer(found: list[str], event: dict[str, object]) -> list[str]:
    """Hosts write transcripts asynchronously; the payload's final answer may be newer."""
    final = str(event.get(KEY_FINAL) or "").strip()
    rendered = f"assistant: {final}" if final else ""
    if rendered and not any(final in item for item in found):
        return [*found, rendered]
    return found
