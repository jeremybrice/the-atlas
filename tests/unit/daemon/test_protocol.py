import tempfile
from atlas.daemon.protocol import (
    encode_message,
    decode_message,
    DaemonSocketServer,
    DaemonSocketClient,
)
from atlas.contracts.types import DaemonCommand, DaemonResponse


def test_encode_decode_command():
    cmd = DaemonCommand(command="goal", payload={"goal_text": "test"})
    encoded = encode_message(cmd)
    decoded = decode_message(encoded)
    assert decoded["command"] == "goal"
    assert decoded["payload"]["goal_text"] == "test"


def test_encode_decode_response():
    resp = DaemonResponse(command_id="abc", status="ok", payload={"result": "done"})
    encoded = encode_message(resp)
    decoded = decode_message(encoded)
    assert decoded["status"] == "ok"


async def test_server_client_roundtrip(tmp_path):
    # Use a short temp path to avoid AF_UNIX path length limits
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"

    async def handler(data: dict) -> dict:
        return {
            "command_id": data["command_id"],
            "status": "ok",
            "payload": {"echo": data["command"]},
        }

    server = DaemonSocketServer(socket_path, handler)
    await server.start()
    try:
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="ping"))
        assert resp["status"] == "ok"
        assert resp["payload"]["echo"] == "ping"
    finally:
        await server.stop()
