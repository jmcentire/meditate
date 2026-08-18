from __future__ import annotations

import pytest

from meditate.redact import sanitize_text, surviving_high_confidence


@pytest.mark.parametrize(
    ("sample", "kind"),
    [
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "credential_header"),
        ("Cookie: session=abcdefghijklmnop", "credential_header"),
        ("api_key=sk-ant-abcdefghijklmnopqrstuvwxyz", "credential_assignment"),
        ("https://alice:correcthorsebattery@example.test/path", "url_userinfo"),
        ("eyJabcdefgh.abcdefghijkl.abcdefghijkl", "jwt"),
        (
            "-----BEGIN PRIVATE KEY-----\nabcdefghi123456789\n-----END PRIVATE KEY-----",
            "private_key",
        ),
    ],
)
def test_high_confidence_secrets_are_redacted(sample: str, kind: str) -> None:
    sanitized = sanitize_text(sample, max_chars=5_000)
    assert sample not in sanitized.text
    assert any(
        finding.kind == kind and finding.confidence == "high" for finding in sanitized.findings
    )
    assert not surviving_high_confidence(sanitized.text)


def test_uuid_and_high_entropy_are_redacted_without_excluding_record() -> None:
    sample = (
        "session 123e4567-e89b-42d3-a456-426614174000 used "
        "A9b8C7d6E5f4G3h2I1j0K9l8M7n6O5p4Q3r2S1t0U9v8"
    )
    sanitized = sanitize_text(sample, max_chars=5_000)
    assert "123e4567" not in sanitized.text
    assert sanitized.findings
    assert not sanitized.has_high_confidence


def test_truncation_keeps_both_ends_and_never_reintroduces_secret() -> None:
    value = "start " + ("ordinary text " * 100) + " password=abcdefghijk end"
    sanitized = sanitize_text(value, max_chars=120)
    assert sanitized.truncated
    assert sanitized.text.startswith("start")
    assert sanitized.text.endswith(" end")
    assert "abcdefghijk" not in sanitized.text
