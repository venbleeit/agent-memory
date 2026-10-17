"""Red team: a credential pasted into a session must never become durable memory."""

import json

import pytest
from agent_memory.adapters import capture as capture_module
from agent_memory.adapters import hook_entry
from agent_memory.core import redaction, sessions

pytestmark = pytest.mark.redteam

TOKEN = "ghp_" + "Zq8Lw3Nv5Rt7Yx9Bc2Df4Gh6Jk1Mp0Qs3Ux7Wa"
PASSWORD = "Tr0ub4dor&3"


def _durable_text(store) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in store.root.rglob("*")
        if path.is_file() and ".index" not in path.parts and ".git" not in path.parts
    )


def test_a_captured_token_reaches_neither_archive_nor_distill_prompt(store):
    items = [f"user: push with {TOKEN} please", f"assistant: set password={PASSWORD} done"]

    result = capture_module.capture(store, "leaky-session", items)

    durable = _durable_text(store)
    assert TOKEN not in durable and PASSWORD not in durable
    assert TOKEN not in result.instruction and PASSWORD not in result.instruction
    assert len(sessions.read(store.layout, "leaky-session")) == len(items)


def test_a_memory_write_carrying_a_token_is_stored_redacted(store):
    store.record(
        type="experience",
        abstract=f"Deploy uses token {TOKEN}",
        body=f"Run the deploy with GITHUB_TOKEN={TOKEN} and password: {PASSWORD}",
        provenance=[f"user said the token is {TOKEN}"],
        name="deploy-token-note",
    )

    durable = _durable_text(store)
    assert TOKEN not in durable and PASSWORD not in durable
    assert "deploy-token-note" in {record.name for record in store.records()}


def test_a_hook_boundary_redacts_items_supplied_by_the_host(store):
    event = {
        "hook_event_name": "Stop",
        "session_id": "hooked",
        "items": [json.dumps({"role": "user", "content": f"token {TOKEN}"})],
    }

    hook_entry.handle(store, event, launch=lambda *_: False)

    assert TOKEN not in _durable_text(store)


def test_scan_reports_existing_hits_by_location_without_the_value(store):
    store.config.redaction.enabled = False
    capture_module.capture(store, "before-redaction", [f"user: {TOKEN}"])
    store.config.redaction.enabled = True

    hits = redaction.scan(store)

    assert [hit.kind for hit in hits] == ["github-token"]
    assert hits[0].path.name.startswith("before-redaction")
    assert hits[0].line >= 1
    assert TOKEN not in json.dumps([hit.as_dict() for hit in hits])
    assert TOKEN in _durable_text(store)
