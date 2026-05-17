"""
KNX connection manager wrapping xknx.
Handles connect/disconnect, telegram receive callbacks and value sending.
"""

import asyncio
import logging
import struct
from typing import Any, Callable, List, Optional

from xknx import XKNX
from xknx.dpt import DPTArray, DPTBinary
from xknx.io import ConnectionConfig, ConnectionType
from xknx.telegram import GroupAddress, Telegram, TelegramDirection
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

logger = logging.getLogger(__name__)


class KNXManager:
    """Singleton-style wrapper around xknx."""

    def __init__(self) -> None:
        self._xknx: Optional[XKNX] = None
        self.connected: bool = False
        self.gateway_host: Optional[str] = None
        self.gateway_port: int = 3671
        self.connection_type: str = "tunneling"
        self._error: Optional[str] = None
        self._callbacks: List[Callable] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def add_telegram_callback(self, cb: Callable) -> None:
        self._callbacks.append(cb)

    def remove_telegram_callback(self, cb: Callable) -> None:
        self._callbacks.discard(cb) if hasattr(self._callbacks, "discard") else None
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    async def connect(
        self,
        host: str,
        port: int = 3671,
        connection_type: str = "tunneling",
    ) -> None:
        await self.disconnect()
        self.gateway_host = host
        self.gateway_port = port
        self.connection_type = connection_type
        self._error = None

        conn_type = (
            ConnectionType.TUNNELING
            if connection_type == "tunneling"
            else ConnectionType.ROUTING
        )
        conn_cfg = ConnectionConfig(
            connection_type=conn_type,
            gateway_ip=host if connection_type == "tunneling" else None,
            gateway_port=port,
        )

        self._xknx = XKNX(
            connection_config=conn_cfg,
            telegram_received_cb=self._on_telegram,
        )

        try:
            await self._xknx.start()
            self.connected = True
            logger.info("Connected to KNX gateway %s:%d (%s)", host, port, connection_type)
        except Exception as exc:
            self.connected = False
            self._error = str(exc)
            logger.error("KNX connection failed: %s", exc)
            raise

    async def disconnect(self) -> None:
        if self._xknx:
            try:
                await self._xknx.stop()
            except Exception as exc:
                logger.warning("Error on KNX disconnect: %s", exc)
            finally:
                self._xknx = None
                self.connected = False

    async def send_value(
        self, group_address: str, value: Any, dpt: Optional[str] = None
    ) -> None:
        if not self.connected or not self._xknx:
            raise RuntimeError("Not connected to KNX gateway")

        payload = self._encode(value, dpt)
        telegram = Telegram(
            destination_address=GroupAddress(group_address),
            payload=GroupValueWrite(payload),
            direction=TelegramDirection.OUTGOING,
        )
        self._xknx.telegrams.put_nowait(telegram)
        logger.debug("Sent %r → %s", value, group_address)

    async def read_value(self, group_address: str) -> None:
        if not self.connected or not self._xknx:
            raise RuntimeError("Not connected to KNX gateway")

        telegram = Telegram(
            destination_address=GroupAddress(group_address),
            payload=GroupValueRead(),
            direction=TelegramDirection.OUTGOING,
        )
        self._xknx.telegrams.put_nowait(telegram)

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "gateway_host": self.gateway_host,
            "gateway_port": self.gateway_port,
            "connection_type": self.connection_type,
            "error": self._error,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _on_telegram(self, telegram: Telegram) -> None:
        """Dispatched by xknx for every incoming telegram."""
        try:
            if telegram.direction != TelegramDirection.INCOMING:
                return

            payload = telegram.payload
            if not isinstance(payload, (GroupValueWrite, GroupValueResponse)):
                return

            apdu = payload.value
            if isinstance(apdu, DPTBinary):
                raw = bytes([apdu.value])
            elif isinstance(apdu, DPTArray):
                raw = bytes(apdu.value)
            else:
                raw = b""

            addr = str(telegram.destination_address)

            for cb in list(self._callbacks):
                try:
                    await cb(addr, raw)
                except Exception as exc:
                    logger.error("Telegram callback error: %s", exc)

        except Exception as exc:
            logger.error("Error processing telegram: %s", exc)

    # ── Value encoding ────────────────────────────────────────────────────────

    def _encode(self, value: Any, dpt: Optional[str]) -> Any:
        if dpt is None:
            # best-effort
            if isinstance(value, bool):
                return DPTBinary(int(value))
            if isinstance(value, (int, float)):
                if 0 <= float(value) <= 1:
                    return DPTBinary(int(value))
                return DPTArray([int(value) & 0xFF])
            return DPTBinary(0)

        main = int(dpt.split(".")[0]) if "." in dpt else int(dpt)

        if main == 1:
            return DPTBinary(1 if value else 0)

        if main == 3:
            # 4-bit relative: encode as 1 byte (direction + step)
            return DPTArray([int(value) & 0x0F])

        if main == 5:
            if dpt == "5.001":
                # 0–100 % → 0–255
                v = max(0, min(100, float(value)))
                return DPTArray([round(v * 255 / 100)])
            return DPTArray([int(value) & 0xFF])

        if main == 9:
            from .categorizer import _dpt9_encode
            return DPTArray(_dpt9_encode(float(value)))

        if main == 13:
            # 4-byte signed integer
            encoded = struct.pack('>i', int(value))
            return DPTArray(list(encoded))

        if main == 14:
            return DPTArray(list(struct.pack('>f', float(value))))

        # Generic fallback
        if isinstance(value, (list, tuple)):
            return DPTArray([int(b) & 0xFF for b in value])
        return DPTArray([int(value) & 0xFF])
