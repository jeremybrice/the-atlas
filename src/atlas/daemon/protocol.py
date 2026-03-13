"""Daemon socket protocol -- JSON-over-Unix-socket with length prefix."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

HEADER_FORMAT = "!I"  # 4-byte unsigned int, network byte order
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def encode_message(obj: Any) -> bytes:
    data = json.dumps(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj).encode()
    return struct.pack(HEADER_FORMAT, len(data)) + data


def decode_message(data: bytes) -> dict:
    # Skip the length-prefix header if present
    if len(data) > HEADER_SIZE:
        (length,) = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        if length == len(data) - HEADER_SIZE:
            data = data[HEADER_SIZE:]
    return json.loads(data)


async def _read_message(reader: asyncio.StreamReader) -> dict | None:
    header = await reader.readexactly(HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    payload = await reader.readexactly(length)
    return json.loads(payload)


async def _write_message(writer: asyncio.StreamWriter, data: dict) -> None:
    encoded = json.dumps(data).encode()
    writer.write(struct.pack(HEADER_FORMAT, len(encoded)) + encoded)
    await writer.drain()


class DaemonSocketServer:
    def __init__(self, socket_path: str, handler: Callable[[dict], Coroutine[Any, Any, dict]]):
        self._socket_path = socket_path
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        Path(self._socket_path).unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(self._handle_client, path=self._socket_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        Path(self._socket_path).unlink(missing_ok=True)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await _read_message(reader)
            if request:
                response = await self._handler(request)
                await _write_message(writer, response)
        except Exception as e:
            logger.error("Socket handler error: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()


class DaemonSocketClient:
    def __init__(self, socket_path: str):
        self._socket_path = socket_path

    async def send(self, command: Any) -> dict:
        reader, writer = await asyncio.open_unix_connection(self._socket_path)
        try:
            encoded = json.dumps(asdict(command) if hasattr(command, "__dataclass_fields__") else command).encode()
            writer.write(struct.pack(HEADER_FORMAT, len(encoded)) + encoded)
            await writer.drain()
            response = await _read_message(reader)
            return response
        finally:
            writer.close()
            await writer.wait_closed()
