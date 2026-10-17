"""Credentials never become memory: every durable text passes through one Redactor."""

from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import TYPE_CHECKING

from .config import RedactionConfig
from .record import MemoryRecord

if TYPE_CHECKING:
    from .store import Store

SECRET_GROUP = "secret"
CUSTOM_KIND = "custom"
KIND_PLACEHOLDER = "{kind}"
SECRET_KEY_NAMES = (
    r"password|passwd|pwd|secret|token|credential|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|(?<![A-Za-z])pat"
)
SECRET_VALUE_MIN_CHARS = 6

CATALOGUE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
    ),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("provider-api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("bearer", re.compile(r"(?i)\bbearer\s+(?P<secret>[A-Za-z0-9._~+/=-]{6,})")),
    ("url-credential", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:/@]+:(?P<secret>[^\s@/]+)@")),
    (
        "secret-assignment",
        re.compile(
            rf"(?i)[\w.-]*(?:{SECRET_KEY_NAMES})s?\b[\"']?\s*[:=]\s*[\"']?"
            rf"(?P<secret>[^\s\"',;]{{{SECRET_VALUE_MIN_CHARS},}})"
        ),
    ),
)


@dataclasses.dataclass(frozen=True)
class Hit:
    kind: str
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class ScanHit:
    path: pathlib.Path
    line: int
    kind: str

    def as_dict(self) -> dict[str, object]:
        return {"path": str(self.path), "line": self.line, "kind": self.kind}


class Redactor:
    def __init__(self, config: RedactionConfig):
        self._config = config
        self._patterns = (
            *CATALOGUE,
            *((CUSTOM_KIND, re.compile(pattern)) for pattern in config.patterns),
        )
        self._redacted_prefix = config.placeholder.split(KIND_PLACEHOLDER)[0]

    def find(self, text: str) -> list[Hit]:
        if not self._config.enabled or not text:
            return []
        accepted: list[Hit] = []
        for kind, pattern in self._patterns:
            for match in pattern.finditer(text):
                hit = _span(kind, match)
                if text.startswith(self._redacted_prefix, hit.start):
                    continue
                if any(hit.start < other.end and other.start < hit.end for other in accepted):
                    continue
                accepted.append(hit)
        return sorted(accepted, key=lambda hit: hit.start)

    def redact(self, text: str) -> str:
        pieces: list[str] = []
        cursor = 0
        for hit in self.find(text):
            pieces += [text[cursor : hit.start], self._config.placeholder.format(kind=hit.kind)]
            cursor = hit.end
        return "".join(pieces) + text[cursor:]

    def redact_record(self, record: MemoryRecord) -> None:
        record.abstract = self.redact(record.abstract)
        record.body = self.redact(record.body)
        record.fields = {
            key: self.redact(value) if isinstance(value, str) else value
            for key, value in record.fields.items()
        }


def scan(store: Store) -> list[ScanHit]:
    """Read-only: report where secrets already sit, never what they are."""
    redactor = Redactor(store.config.redaction)
    layout = store.layout
    candidates = {*layout.truth_files(), layout.memory_index}
    if layout.archive.exists():
        candidates.update(path for path in layout.archive.rglob("*") if path.is_file())
    hits: list[ScanHit] = []
    for path in sorted(candidate for candidate in candidates if candidate.is_file()):
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits += [
            ScanHit(path.relative_to(layout.root), text.count("\n", 0, hit.start) + 1, hit.kind)
            for hit in redactor.find(text)
        ]
    return hits


def _span(kind: str, match: re.Match[str]) -> Hit:
    if SECRET_GROUP in match.re.groupindex:
        return Hit(kind, match.start(SECRET_GROUP), match.end(SECRET_GROUP))
    return Hit(kind, match.start(), match.end())
