"""Minimal MQTT client for Fotile App control commands."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any


def _encode_string(value: str) -> bytes:
    raw = value.encode()
    return struct.pack(">H", len(raw)) + raw


def _packet(packet_type: int, flags: int, payload: bytes) -> bytes:
    header = bytes([(packet_type << 4) | flags])
    length = len(payload)
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            encoded.append(digit | 0x80)
        else:
            encoded.append(digit)
            break
    return header + encoded + payload


class FotileMqtt:
    """Publish one control command using the Fotile App MQTT protocol."""

    def __init__(
        self,
        client_id: str,
        username: str,
        password: str,
    ) -> None:
        self.client_id = client_id
        self.username = username
        self.password = password
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self, host: str, port: int = 1883, keepalive: int = 30) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=15,
        )
        self._writer = writer
        variable = (
            _encode_string("MQTT") + bytes([4, 0xC2]) + struct.pack(">H", keepalive)
        )
        payload = (
            _encode_string(self.client_id)
            + _encode_string(self.username)
            + _encode_string(self.password)
        )
        writer.write(_packet(1, 0, variable + payload))
        await writer.drain()

        connack = await asyncio.wait_for(reader.readexactly(4), timeout=15)
        if connack[0] >> 4 != 2 or connack[3] != 0:
            writer.close()
            self._writer = None
            raise ConnectionError(f"Fotile MQTT connection rejected: {connack!r}")

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._writer is None or self._writer.is_closing():
            raise ConnectionError("Fotile MQTT connection is not open")
        body = json.dumps(payload, separators=(",", ":")).encode()
        self._writer.write(_packet(3, 0, _encode_string(topic) + body))
        await self._writer.drain()
        # QoS 0 has no acknowledgement. Keep the session open long enough for
        # the broker to hand the command to the device.
        await asyncio.sleep(1)

    async def disconnect(self) -> None:
        writer = self._writer
        self._writer = None
        if writer is None:
            return
        try:
            writer.write(_packet(14, 0, b""))
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
