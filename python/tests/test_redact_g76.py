"""G76: redact 补 AWS AKIA / GCP AIza / JWT / PEM 私钥块遮罩。"""

from __future__ import annotations

from audit.redact import command_summary, redact_text


def test_redacts_akia() -> None:
    out = redact_text("key=AKIAIOSFODNN7EXAMPLE rest")
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_redacts_aiza_gcp() -> None:
    out = redact_text("gcp_key=AIzaSyD8vR4qFwLkJmCxYpRtzZ4kLmNpQrStUvWxYz rest")
    assert "AIzaSyD8vR4qFwLkJmCxYpRtzZ4kLmNpQrStUvWxYz" not in out


def test_redacts_jwt() -> None:
    tok = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    out = redact_text(f"Authorization: Bearer {tok}")
    assert tok not in out


def test_redacts_pem_block() -> None:
    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJT\n"
        "-----END PRIVATE KEY-----"
    )
    out = redact_text(pem)
    assert "PRIVATE KEY" not in out
    assert "MIIEvQIB" not in out


def test_keeps_plain_text_and_summary() -> None:
    assert redact_text("git status") == "git status"
    out = command_summary("git diff -- src/a.py")
    assert "git diff" in out
