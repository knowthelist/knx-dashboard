from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


# ── Categories ───────────────────────────────────────────────────────────────

class DeviceCategory(str, Enum):
    LIGHT = "light"
    BLIND = "blind"
    HEATING = "heating"
    SENSOR = "sensor"
    SPRINKLER = "sprinkler"
    MEDIA = "media"
    UNKNOWN = "unknown"


class ConnectionType(str, Enum):
    TUNNELING = "tunneling"
    ROUTING = "routing"


# ── Request / Response models ─────────────────────────────────────────────────

class KNXConfig(BaseModel):
    gateway_host: str
    gateway_port: int = 3671
    connection_type: ConnectionType = ConnectionType.TUNNELING


class Device(BaseModel):
    id: Optional[int] = None
    group_address: str
    name: str
    category: DeviceCategory = DeviceCategory.UNKNOWN
    dpt: Optional[str] = None
    dpt_name: Optional[str] = None
    value: Optional[Any] = None
    unit: Optional[str] = None
    last_seen: Optional[str] = None
    auto_detected: bool = True
    writable: bool = True
    readable: bool = True


class DeviceCreate(BaseModel):
    group_address: str
    name: str
    category: DeviceCategory = DeviceCategory.UNKNOWN
    dpt: Optional[str] = None
    writable: bool = True
    readable: bool = True


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[DeviceCategory] = None
    dpt: Optional[str] = None
    writable: Optional[bool] = None
    readable: Optional[bool] = None


class ControlRequest(BaseModel):
    value: Any
    dpt: Optional[str] = None


class ConnectionStatus(BaseModel):
    connected: bool
    gateway_host: Optional[str] = None
    gateway_port: Optional[int] = None
    connection_type: Optional[str] = None
    error: Optional[str] = None


class WSMessage(BaseModel):
    type: str
    data: Any
