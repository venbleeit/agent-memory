"""A Windows host reaches the WSL install; one operating system serializes every writer."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re
import shlex
import subprocess
import sys

from agent_memory.core.config import Config
from agent_memory.core.errors import FieldError, ValidationError

LAUNCHER = "wsl.exe"
DISTRO_FLAG = "-d"
ARGUMENT_SEPARATOR = "--"
DISTRO_ENV = "WSL_DISTRO_NAME"
DIALECT = "windows"
PATH_DIALECT_FLAG = "--path-dialect"
CLI_COMMAND = "mem"
STORE_FLAG = "--store"
PATH_KEYS = ("transcript_path", "agent_transcript_path")
SAFE_DISTRO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DRIVE_PATH = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")
WSL_SHARE_PATH = re.compile(
    r"^[\\/]{2}(?:wsl\$|wsl\.localhost)[\\/][^\\/]+(?P<rest>[\\/].*)?$", re.IGNORECASE
)
WINDOWS_HOME_COMMAND = ("cmd.exe", "/c", "echo %USERPROFILE%")
CLAUDE_SETTINGS = pathlib.Path(".claude") / "settings.json"
PROBE_TIMEOUT_SECONDS = 10


@dataclasses.dataclass(frozen=True)
class WindowsBridge:
    distro: str

    def wrap(self, argv: list[str]) -> list[str]:
        return [LAUNCHER, DISTRO_FLAG, self.distro, ARGUMENT_SEPARATOR, *argv]

    def invocation(self, store_root: pathlib.Path) -> str:
        cli = str(pathlib.Path(sys.executable).parent / CLI_COMMAND)
        return shlex.join(self.wrap([cli, STORE_FLAG, str(pathlib.Path(store_root).resolve())]))


def detect(environment: dict[str, str] | None = None) -> WindowsBridge:
    env = os.environ if environment is None else environment
    distro = env.get(DISTRO_ENV, "")
    if not SAFE_DISTRO.match(distro):
        raise ValidationError(
            [FieldError("windows", "run setup inside WSL so the distro name is known")]
        )
    return WindowsBridge(distro=distro)


def to_wsl_path(value: str, mount_root: str) -> str:
    share = WSL_SHARE_PATH.match(value)
    if share:
        return (share.group("rest") or "/").replace("\\", "/")
    drive = DRIVE_PATH.match(value)
    if drive:
        rest = drive.group("rest").replace("\\", "/")
        return f"{mount_root.rstrip('/')}/{drive.group('drive').lower()}/{rest}"
    return value


def translate_event(event: dict[str, object], config: Config) -> dict[str, object]:
    root = config.write.windows_mount_root
    return {
        key: to_wsl_path(value, root) if key in PATH_KEYS and isinstance(value, str) else value
        for key, value in event.items()
    }


def windows_settings_path(config: Config) -> pathlib.Path:
    try:
        completed = subprocess.run(
            list(WINDOWS_HOME_COMMAND),
            capture_output=True,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError(
            [FieldError("windows", f"could not ask Windows for the user profile: {error}")]
        ) from error
    profile = completed.stdout.strip()
    if completed.returncode != 0 or not DRIVE_PATH.match(profile):
        raise ValidationError(
            [FieldError("windows", "Windows did not report a user profile; pass --settings")]
        )
    return pathlib.Path(to_wsl_path(profile, config.write.windows_mount_root)) / CLAUDE_SETTINGS
