import pytest
from agent_memory.core import redaction
from agent_memory.core.config import Config, RedactionConfig


def _shaped(prefix: str, length: int, alphabet: str = "aB3dE5gH7jK9mN1pQ") -> str:
    body = (alphabet * (length // len(alphabet) + 1))[:length]
    return prefix + body


SHAPED_SECRETS = {
    "github-token": _shaped("ghp_", 36),
    "github-fine-grained-token": _shaped("github_pat_", 82),
    "aws-access-key": _shaped("AKIA", 16, "ABCDEFGHIJKLMNOP2345"),
    "provider-api-key": _shaped("sk-ant-api03-", 40),
    "slack-token": _shaped("xoxb-", 40, "1234567890abcdef-"),
    "google-api-key": _shaped("AIza", 35),
    "jwt": "eyJ" + _shaped("", 30) + ".eyJ" + _shaped("", 40) + "." + _shaped("", 43),
}


def _redactor(**overrides: object) -> redaction.Redactor:
    return redaction.Redactor(RedactionConfig(**overrides))


@pytest.mark.parametrize("kind", sorted(SHAPED_SECRETS))
def test_each_catalogue_shape_is_removed_and_named(kind):
    secret = SHAPED_SECRETS[kind]
    text = f"use {secret} for the deploy"

    clean = _redactor().redact(text)

    assert secret not in clean
    assert kind in clean
    assert clean.startswith("use ") and clean.endswith(" for the deploy")


@pytest.mark.parametrize(
    "text, secret",
    [
        ("Authorization: Bearer abc.DEF-123_xyz", "abc.DEF-123_xyz"),
        ("postgres://admin:hunter2pass@db.local:5432/app", "hunter2pass"),
        ("Server=db;User Id=sa;Password=Sup3rS3cret!;", "Sup3rS3cret!"),
        ("export GITHUB_PAT=plainvalue123", "plainvalue123"),
        ('api_key: "q1w2e3r4t5"', "q1w2e3r4t5"),
        ("client_secret = zx9cv8bn7", "zx9cv8bn7"),
    ],
)
def test_credentials_in_context_lose_only_their_value(text, secret):
    clean = _redactor().redact(text)

    assert secret not in clean
    assert clean.startswith(text.split(secret)[0])


def test_private_key_blocks_are_removed_whole():
    block = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\nAAAA\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )

    clean = _redactor().redact(f"key:\n{block}\ndone")

    assert "b3BlbnNzaC1rZXk" not in clean
    assert "BEGIN" not in clean
    assert clean.endswith("done")


def test_redaction_is_idempotent_and_finds_nothing_in_its_own_output():
    text = " ".join(SHAPED_SECRETS.values()) + " password=abc123 Bearer tok.en"
    redactor = _redactor()

    once = redactor.redact(text)

    assert redactor.redact(once) == once
    assert redactor.find(once) == []


def test_plain_prose_is_untouched():
    text = "The token bucket refills every second; the password policy needs 12 characters."

    assert _redactor().redact(text) == text


def test_configured_patterns_extend_the_catalogue():
    redactor = _redactor(patterns=[r"ESTATE-\d{6}"])

    clean = redactor.redact("door code ESTATE-123456 today")

    assert "123456" not in clean
    assert redaction.CUSTOM_KIND in clean


def test_disabled_redaction_returns_text_verbatim():
    secret = SHAPED_SECRETS["github-token"]

    assert _redactor(enabled=False).redact(secret) == secret


def test_find_reports_kind_and_span_without_needing_the_value():
    secret = SHAPED_SECRETS["aws-access-key"]
    text = f"key {secret}"

    hits = _redactor().find(text)

    assert [hit.kind for hit in hits] == ["aws-access-key"]
    assert text[hits[0].start : hits[0].end] == secret


@pytest.mark.parametrize(
    "overrides",
    [{"patterns": ["("]}, {"patterns": [7]}, {"placeholder": "[gone]"}, {"enabled": "yes"}],
)
def test_malformed_redaction_config_is_rejected_at_load(tmp_path, overrides):
    config = Config.default()
    for key, value in overrides.items():
        setattr(config.redaction, key, value)
    config.save(tmp_path)

    with pytest.raises(ValueError):
        Config.load(tmp_path)


def test_backslash_patterns_round_trip_through_disk(tmp_path):
    config = Config.default()
    config.redaction.patterns = [r"ESTATE-\d{6}\b"]
    config.save(tmp_path)

    assert Config.load(tmp_path).redaction.patterns == [r"ESTATE-\d{6}\b"]
