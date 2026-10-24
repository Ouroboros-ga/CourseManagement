import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from tests.unit.agent.test_http_gateway import client_for
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_mcp_real_network_obeys_same_scope_and_lifecycle(campus, monkeypatch):
    from app.core.config import get_settings
    from app.main import create_app

    _, headers, _ = client_for(campus, monkeypatch)
    monkeypatch.setattr(get_settings(), "agent_mcp_enabled", True)
    app = create_app()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        url = f"http://127.0.0.1:{port}/mcp/agent-tools"
        protocol = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
            **headers,
        }
        with httpx.Client(timeout=5) as client:
            assert client.post(url, json={}).status_code == 401
            assert client.get(f"http://127.0.0.1:{port}/health/live").status_code == 200
            initialized = client.post(
                url,
                headers=protocol,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "gateway-test", "version": "1"},
                    },
                },
            )
            assert initialized.status_code == 200, initialized.text
            listing = client.post(
                url,
                headers=protocol,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            names = {t["name"] for t in listing.json()["result"]["tools"]}
            assert "system_probe" in names
            assert "report_attendance_summary" not in names
            response = client.post(
                url,
                headers=protocol,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "system_probe", "arguments": {}},
                },
            )
            result = response.json()["result"]
            assert result["structuredContent"]["data"] == {"contract_version": "v1"}
            hidden = client.post(
                url,
                headers=protocol,
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "report_attendance_summary", "arguments": {}},
                },
            )
            assert hidden.json()["result"]["isError"]
            bad_origin = client.post(
                url,
                headers={**protocol, "Origin": "https://evil.invalid"},
                json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
            )
            assert bad_origin.status_code in (403, 421)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    assert not thread.is_alive()
