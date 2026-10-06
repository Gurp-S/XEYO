"""G76: redact 补 AWS AKIA / GCP AIza / JWT / PEM 私钥块遮罩。"""

from __future__ import annotations

from audit.redact import command_summary, redact_text, scrub_audit_fields


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


# ---------------------------------------------------------------------------
# 09-10 P1-16：嵌套 dict/list 内的敏感键必须逐层打码（不许明文落审计）
# ---------------------------------------------------------------------------


def test_scrub_audit_fields_masks_nested_secrets() -> None:
    out = scrub_audit_fields(
        {
            "tool_input": {
                "headers": {"authorization": "Bearer sk-abcdef1234567890"},
                "command": "curl -H 'X-Key: sk-abcdef1234567890'",
                "tags": ["alpha", "beta"],
                "file_path": "/tmp/plain.txt",
            },
            "note": "neutral",
        }
    )
    ti = out["tool_input"]
    assert ti["headers"]["authorization"] == "***"
    assert "sk-abcdef1234567890" not in ti["command"]
    # 规则=键名命中（与顶层语义一致）；中性键原样，不做全串遮罩
    # （那会把中性字段里的 32+ 位十六进制散列也一并吞掉）。
    assert ti["tags"] == ["alpha", "beta"]
    assert ti["file_path"] == "/tmp/plain.txt"
    assert out["note"] == "neutral"


def test_scrub_audit_fields_depth_is_bounded() -> None:
    """深嵌套不崩溃、不无限递归；浅层（真实工具入参的量级）内必被遮罩。"""
    shallow = {"wrap": {"session": {"token": "sk-abcdef1234567890"}}}
    out = scrub_audit_fields({"tool_input": shallow})
    assert "sk-abcdef1234567890" not in str(out)

    deep: dict = {"token": "sk-abcdef1234567890"}
    for _ in range(30):
        deep = {"wrap": deep}
    scrubbed = scrub_audit_fields({"tool_input": deep})
    assert isinstance(scrubbed, dict)  # 有界返回，不抛栈溢出
