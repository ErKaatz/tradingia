from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from src.execution.base import JournalEntry
from src.execution.mt5_remote import (
    ExecutionProtocolError,
    HttpResponse,
    MT5RemoteExecutionClient,
    RemoteConfig,
)
import src.cli.mt5_remote_cli as cli


@dataclass
class _FakeTransport:
    responses_by_path: dict[str, HttpResponse] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str], float]] = field(default_factory=list)

    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, headers, timeout))
        for path, response in self.responses_by_path.items():
            if path in url:
                return response
        raise AssertionError(f"no fake response configured for URL {url}")

    def post(self, url: str, headers: dict[str, str], timeout: float, json_body: dict) -> HttpResponse:
        raise AssertionError("journal must never POST")


def _response(payload: dict) -> HttpResponse:
    text = json.dumps(payload)
    return HttpResponse(status_code=200, text=text, content_length=len(text.encode()))


def _client(payload: dict) -> MT5RemoteExecutionClient:
    cfg = RemoteConfig(bridge_url="http://127.0.0.1:8765", api_token="test-token")
    return MT5RemoteExecutionClient(
        cfg,
        transport=_FakeTransport({"/v1/journal": _response(payload)}),
    )


def test_journal_parses_read_only_entries():
    client = _client({
        "entries": [{
            "id": 7,
            "request_id": "req-1",
            "client_order_id": "cid-1",
            "timestamp": "2026-09-03T15:34:20+00:00",
            "action": "place_order.filled",
            "payload": {"status": "filled", "fill_price": "1.16269"},
        }]
    })
    entries = client.journal(2)
    assert len(entries) == 1
    e = entries[0]
    assert e.entry_id == 7
    assert e.client_order_id == "cid-1"
    assert e.timestamp == datetime(2026, 9, 3, 15, 34, 20, tzinfo=timezone.utc)
    assert e.payload["status"] == "filled"


def test_journal_rejects_bad_payload_shape():
    client = _client({"entries": [{"id": 1}]})
    with pytest.raises(ExecutionProtocolError):
        client.journal()


def test_journal_limit_validation():
    client = _client({"entries": []})
    with pytest.raises(ValueError):
        client.journal(0)
    with pytest.raises(ValueError):
        client.journal(1001)


def test_cli_journal_prints_entries(monkeypatch, capsys):
    class FakeClient:
        def journal(self, limit=20):
            assert limit == 5
            return (JournalEntry(
                entry_id=9,
                request_id="req-x",
                client_order_id="cid-x",
                timestamp=datetime(2026, 9, 3, 15, 34, 20, tzinfo=timezone.utc),
                action="close_position.filled",
                payload={"status": "filled", "fill_price": "1.16230"},
            ),)

    monkeypatch.setattr(cli, "_build_client", lambda: FakeClient())

    class Args:
        limit = 5

    cli.cmd_journal(Args())
    out = capsys.readouterr().out
    assert "close_position.filled" in out
    assert "cid-x" in out
    assert '"fill_price":"1.16230"' in out
