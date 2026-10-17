"""A Windows host reaches the WSL install through one bridge; the core never runs on Windows."""

from __future__ import annotations

import io
import json

import pytest
from agent_memory.adapters import doctor, hook_entry, host_setup, moments, setup, windows_bridge
from agent_memory.core import prompts, sessions
from agent_memory.core.errors import ValidationError
from agent_memory.core.store import Store

HOST = moments.HOST_CLAUDE_CODE
DISTRO = "Ubuntu"
FOREIGN_HOOK = {
    "matcher": "*",
    "hooks": [{"type": "command", "command": "powershell -File C:\\hooks\\state.ps1"}],
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(setup, "probe", lambda selected: f"{selected} 1.0")
    monkeypatch.setattr(
        doctor,
        "_live_reasoner_check",
        lambda _store, _host, operation: doctor.Check(f"{operation}_LIVE_OK", True, "fixture"),
    )


@pytest.fixture
def bridge():
    return windows_bridge.WindowsBridge(distro=DISTRO)


@pytest.fixture
def windows_home(tmp_path):
    home = tmp_path / "Users" / "someone"
    (home / ".claude").mkdir(parents=True)
    return home


@pytest.mark.parametrize(
    "windows, expected",
    [
        ("C:\\Users\\someone\\.claude\\s.jsonl", "/mnt/c/Users/someone/.claude/s.jsonl"),
        ("d:/work/t.jsonl", "/mnt/d/work/t.jsonl"),
        ("\\\\wsl.localhost\\Ubuntu\\home\\u\\t.jsonl", "/home/u/t.jsonl"),
        ("\\\\wsl$\\Ubuntu\\home\\u", "/home/u"),
        ("/home/u/already.jsonl", "/home/u/already.jsonl"),
        ("", ""),
    ],
)
def test_windows_paths_translate_to_their_wsl_mount(windows, expected):
    assert windows_bridge.to_wsl_path(windows, "/mnt") == expected


def test_the_mount_root_comes_from_config(store):
    store.config.write.windows_mount_root = "/win"

    event = windows_bridge.translate_event({"transcript_path": "C:\\a\\b.jsonl"}, store.config)

    assert event["transcript_path"] == "/win/c/a/b.jsonl"


def test_a_bridged_hook_reads_a_transcript_named_by_its_windows_path(store, tmp_path, monkeypatch):
    mount = tmp_path / "mnt"
    transcript = mount / "c" / "Users" / "someone" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"role": "user", "content": "bridged hello"}) + "\n")
    store.config.write.windows_mount_root = str(mount)
    store.config.write.distill_on_boundary = False
    store.config.save(store.root)
    payload = {
        "hook_event_name": "Stop",
        "session_id": "windows-session",
        "transcript_path": "C:\\Users\\someone\\session.jsonl",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    hook_entry.main(
        ["--host", HOST, "--store", str(store.root), "--path-dialect", windows_bridge.DIALECT]
    )

    texts = [message.text for message in sessions.read(store.layout, "windows-session")]
    assert texts == ["bridged hello"]


def test_bridged_setup_writes_exec_form_hooks_and_preserves_foreign_ones(
    tmp_path, windows_home, bridge
):
    target = windows_home / ".claude" / "settings.json"
    target.write_text(json.dumps({"hooks": {"Stop": [FOREIGN_HOOK]}, "theme": "keep"}))
    store = Store(tmp_path / "store")

    first = host_setup.run(store, HOST, settings_path=target, bridge=bridge)
    once = target.read_bytes()
    host_setup.run(store, HOST, settings_path=target, bridge=bridge)

    assert first["status"] == doctor.READY, first["checks"]
    assert target.read_bytes() == once
    configured = json.loads(once)
    assert configured["theme"] == "keep"
    assert FOREIGN_HOOK in configured["hooks"]["Stop"]
    for event in moments.DIALECTS[HOST]:
        managed = [
            hook
            for entry in configured["hooks"][event]
            for hook in entry["hooks"]
            if setup.HOOK_COMMAND in json.dumps(hook)
        ]
        assert len(managed) == 1
        assert managed[0]["command"] == windows_bridge.LAUNCHER
        arguments = managed[0]["args"]
        assert arguments[: arguments.index("--") + 1] == ["-d", DISTRO, "--"]
        assert windows_bridge.DIALECT in arguments
        assert str(store.root) in arguments


def test_a_native_hook_entry_is_replaced_not_duplicated_by_the_bridge(
    tmp_path, windows_home, bridge
):
    target = windows_home / ".claude" / "settings.json"
    store = Store(tmp_path / "store")
    setup.install(HOST, target, store.root)

    setup.install(HOST, target, store.root, bridge=bridge)

    stop = json.loads(target.read_text())["hooks"]["Stop"]
    assert len([entry for entry in stop if setup.HOOK_COMMAND in json.dumps(entry)]) == 1
    assert windows_bridge.LAUNCHER in json.dumps(stop)


def test_the_bridged_skill_names_the_bridged_command_and_doctor_accepts_it(
    tmp_path, windows_home, bridge
):
    target = windows_home / ".claude" / "settings.json"
    store = Store(tmp_path / "store")

    host_setup.run(store, HOST, settings_path=target, bridge=bridge)

    skill = setup.skill_path(HOST, target).read_text(encoding="utf-8")
    assert skill == prompts.skill(bridge.invocation(store.root))
    assert windows_bridge.LAUNCHER in skill and str(store.root) in skill
    native = doctor.run(store, HOST, settings_path=target, live=False)
    bridged = doctor.run(store, HOST, settings_path=target, live=False, bridge=bridge)
    assert "SKILL_INVALID" in {check.code for check in native.checks}
    assert "SKILL_OK" in {check.code for check in bridged.checks}


def test_bridged_mcp_runs_the_wsl_server_with_the_store_pinned(tmp_path, windows_home, bridge):
    target = windows_home / ".claude" / "settings.json"
    store = Store(tmp_path / "store")

    report = host_setup.run(store, HOST, settings_path=target, mcp=True, bridge=bridge)

    server = json.loads((windows_home / ".claude.json").read_text())["mcpServers"]["agent-memory"]
    assert server["command"] == windows_bridge.LAUNCHER
    assert f"AGENT_MEMORY_STORE={store.root}" in server["args"]
    assert setup.mcp_binary() in server["args"]
    assert "MCP_OK" in {check["code"] for check in report["checks"]}


def test_the_bridge_requires_a_wsl_distro():
    with pytest.raises(ValidationError):
        windows_bridge.detect({})


@pytest.mark.redteam
@pytest.mark.parametrize("distro", ["Ubuntu; rm -rf ~", "a b", "$(whoami)", "-d"])
def test_a_hostile_distro_name_is_refused(distro):
    with pytest.raises(ValidationError):
        windows_bridge.detect({windows_bridge.DISTRO_ENV: distro})
