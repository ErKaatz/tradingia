"""Tests for the central sanitizer (FX Phase 0, Step 4)."""

from __future__ import annotations

from mt5_bridge.sanitize import sanitize_exception, sanitize_message


def test_none_stays_none():
    assert sanitize_message(None) is None


def test_removes_bearer_token():
    result = sanitize_message("failed with Authorization: Bearer abc123secrettoken")
    assert "abc123secrettoken" not in result


def test_removes_password_kv():
    result = sanitize_message("login failed password=hunter2")
    assert "hunter2" not in result


def test_removes_api_key_kv():
    result = sanitize_message("api_key=sk-1234567890 rejected")
    assert "sk-1234567890" not in result


def test_removes_windows_path():
    result = sanitize_message(r"error opening C:\Users\alex\AppData\Local\secret.txt")
    assert r"C:\Users\alex" not in result
    assert "[PATH]" in result


def test_removes_unix_path():
    result = sanitize_message("/home/ale-linux/.mt5/secret/config.ini not found")
    assert "/home/ale-linux" not in result


def test_leaves_plain_text_untouched():
    text = "order_check rejected: insufficient margin"
    assert sanitize_message(text) == text


def test_sanitize_exception_never_includes_traceback_text():
    try:
        raise RuntimeError("boom with token=abcxyz123")
    except RuntimeError as exc:
        result = sanitize_exception(exc)
    assert "abcxyz123" not in result
    assert "Traceback" not in result


def test_sanitize_exception_handles_empty_message():
    try:
        raise RuntimeError()
    except RuntimeError as exc:
        result = sanitize_exception(exc)
    assert "RuntimeError" in result
