"""
FastAPI application – KNX Dashboard backend.

Routes
------
GET  /api/status                  KNX connection status
POST /api/connect                 Connect to KNX gateway
POST /api/disconnect              Disconnect
GET  /api/stats                   Dashboard statistics
GET  /api/devices                 List all devices (optionally filtered by category)
POST /api/devices                 Manually create a device
GET  /api/devices/{id}            Get single device
PUT  /api/devices/{id}            Update name / category / DPT
DELETE /api/devices/{id}          Delete device
POST /api/devices/{id}/control    Send value to KNX group address
POST /api/devices/{id}/read       Request current value from bus
POST /api/import/ets              Upload & import ETS .knxproj file

WS   /ws                          Real-time push (device updates, connection events)
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware

from .categorizer import categorize_by_dpt, decode_raw, infer_dpt
from .device_registry import (
    create_device,
    delete_device,
    get_all_devices,
    get_device_by_id,
    get_devices_by_category,
    init_db,
    update_device,
    update_device_value,
    upsert_auto_device,
    get_config,
    set_config,
)
from .ets_importer import parse_knxproj
from .knx_manager import KNXManager
from .models import (
    ConnectionStatus,
    ControlRequest,
    Device,
    DeviceCategory,
    DeviceCreate,
    DeviceUpdate,
    KNXConfig,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DATABASE_PATH", "/app/data/knx_devices.db")

knx = KNXManager()


# ── WebSocket manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        dead: List[WebSocket] = []
        data = json.dumps(message)
        for ws in list(self._clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


ws_manager = ConnectionManager()


# ── KNX telegram handler ─────────────────────────────────────────────────────

async def _on_telegram(group_address: str, raw: bytes) -> None:
    """Called by KNXManager for every incoming telegram."""
    # Try to decode
    existing = await get_device_by_address_safe(group_address)
    known_dpt = existing.dpt if existing else None
    value, resolved_dpt = decode_raw(raw, known_dpt)

    if not existing:
        # Auto-discover new device
        dpt = resolved_dpt or infer_dpt(raw)
        auto_name = f"Device {group_address}"
        cat, dpt_name, unit = categorize_by_dpt(dpt, auto_name)
        device = Device(
            group_address=group_address,
            name=auto_name,
            category=cat,
            dpt=dpt,
            dpt_name=dpt_name,
            unit=unit,
            value=value,
            auto_detected=True,
        )
        saved = await upsert_auto_device(device, DB_PATH)
    else:
        await update_device_value(group_address, value, DB_PATH)
        saved = existing
        saved.value = value

    await ws_manager.broadcast({
        "type": "device_update",
        "data": saved.model_dump() if saved else {"group_address": group_address, "value": value},
    })


async def get_device_by_address_safe(addr: str) -> Optional[Device]:
    from .device_registry import get_device_by_address
    return await get_device_by_address(addr, DB_PATH)


async def _redecode_stored_values() -> None:
    """Re-decode devices whose stored value is a raw byte list (old decode bug).
    Also re-categorizes auto-detected unknown devices using current name keywords."""
    devices = await get_all_devices(DB_PATH)
    for dev in devices:
        updated = False

        # Fix raw byte lists
        if isinstance(dev.value, list) and dev.dpt:
            try:
                raw = bytes(int(b) for b in dev.value)
                new_val, _ = decode_raw(raw, dev.dpt)
                if not isinstance(new_val, list):
                    await update_device_value(dev.group_address, new_val, DB_PATH)
                    logger.info("Re-decoded %s (%s): %s → %s", dev.group_address, dev.dpt, dev.value, new_val)
                    updated = True
            except Exception as exc:
                logger.debug("Could not re-decode %s: %s", dev.group_address, exc)

        # Re-categorize auto-detected unknown devices
        if dev.auto_detected and dev.category.value == "unknown":
            from .models import DeviceUpdate
            cat, dpt_name, unit = categorize_by_dpt(dev.dpt, dev.name)
            if cat.value != "unknown":
                await update_device(dev.id, DeviceUpdate(category=cat), DB_PATH)
                logger.info("Re-categorized %s → %s", dev.name, cat.value)


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(DB_PATH)
    knx.add_telegram_callback(_on_telegram)

    # Re-decode any values that were stored as raw byte lists (from old bugs)
    await _redecode_stored_values()

    # Auto-connect if gateway configured via env vars
    host = os.environ.get("KNX_GATEWAY_HOST", "").strip()
    if host:
        port = int(os.environ.get("KNX_GATEWAY_PORT", "3671"))
        conn_type = os.environ.get("KNX_CONNECTION_TYPE", "tunneling")
        try:
            await knx.connect(host, port, conn_type)
            await set_config("gateway_host", host, DB_PATH)
            await set_config("gateway_port", str(port), DB_PATH)
            await set_config("connection_type", conn_type, DB_PATH)
        except Exception as exc:
            logger.warning("Auto-connect failed: %s", exc)
    else:
        # Try stored config
        stored_host = await get_config("gateway_host", DB_PATH)
        if stored_host:
            stored_port = int(await get_config("gateway_port", DB_PATH) or "3671")
            stored_type = await get_config("connection_type", DB_PATH) or "tunneling"
            try:
                await knx.connect(stored_host, stored_port, stored_type)
            except Exception as exc:
                logger.warning("Stored-config auto-connect failed: %s", exc)

    yield

    await knx.disconnect()


app = FastAPI(title="KNX Dashboard", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/status", response_model=ConnectionStatus)
async def get_status():
    return knx.status()


@app.post("/api/connect", response_model=ConnectionStatus)
async def connect_knx(cfg: KNXConfig):
    try:
        await knx.connect(cfg.gateway_host, cfg.gateway_port, cfg.connection_type.value)
        await set_config("gateway_host", cfg.gateway_host, DB_PATH)
        await set_config("gateway_port", str(cfg.gateway_port), DB_PATH)
        await set_config("connection_type", cfg.connection_type.value, DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    status = knx.status()
    await ws_manager.broadcast({"type": "connection_status", "data": status})
    return status


@app.post("/api/disconnect", response_model=ConnectionStatus)
async def disconnect_knx():
    await knx.disconnect()
    status = knx.status()
    await ws_manager.broadcast({"type": "connection_status", "data": status})
    return status


@app.get("/api/stats")
async def get_stats():
    devices = await get_all_devices(DB_PATH)
    cats = {c.value: 0 for c in DeviceCategory}
    lights_on = 0
    blinds_open = 0
    temperatures: List[float] = []

    for d in devices:
        cats[d.category.value] += 1
        if d.category == DeviceCategory.LIGHT and d.dpt in ("1.001",):
            if d.value:
                lights_on += 1
        if d.category == DeviceCategory.BLIND and d.dpt in ("1.009",):
            if d.value:
                blinds_open += 1
        if d.category == DeviceCategory.HEATING and d.dpt == "9.001" and d.value is not None:
            try:
                temperatures.append(float(d.value))
            except (TypeError, ValueError):
                pass

    avg_temp = round(sum(temperatures) / len(temperatures), 1) if temperatures else None
    return {
        "total": len(devices),
        "by_category": cats,
        "lights_on": lights_on,
        "blinds_open": blinds_open,
        "avg_temperature": avg_temp,
        "connected": knx.connected,
    }


@app.get("/api/devices", response_model=List[Device])
async def list_devices(category: Optional[str] = Query(None)):
    if category:
        try:
            cat = DeviceCategory(category)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
        return await get_devices_by_category(cat, DB_PATH)
    return await get_all_devices(DB_PATH)


@app.post("/api/devices", response_model=Device, status_code=201)
async def add_device(payload: DeviceCreate):
    try:
        return await create_device(payload, DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/devices/{device_id}", response_model=Device)
async def get_device(device_id: int):
    device = await get_device_by_id(device_id, DB_PATH)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@app.put("/api/devices/{device_id}", response_model=Device)
async def update_device_route(device_id: int, upd: DeviceUpdate):
    device = await update_device(device_id, upd, DB_PATH)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    await ws_manager.broadcast({"type": "device_update", "data": device.model_dump()})
    return device


@app.delete("/api/devices/{device_id}", status_code=204)
async def delete_device_route(device_id: int):
    ok = await delete_device(device_id, DB_PATH)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")


@app.post("/api/devices/{device_id}/control")
async def control_device(device_id: int, req: ControlRequest):
    if not knx.connected:
        raise HTTPException(status_code=503, detail="Not connected to KNX gateway")

    device = await get_device_by_id(device_id, DB_PATH)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.writable:
        raise HTTPException(status_code=403, detail="Device is read-only")

    dpt = req.dpt or device.dpt
    try:
        await knx.send_value(device.group_address, req.value, dpt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    await update_device_value(device.group_address, req.value, DB_PATH)
    device.value = req.value
    await ws_manager.broadcast({"type": "device_update", "data": device.model_dump()})
    return {"status": "sent", "group_address": device.group_address, "value": req.value}


@app.post("/api/devices/{device_id}/read")
async def read_device(device_id: int):
    if not knx.connected:
        raise HTTPException(status_code=503, detail="Not connected to KNX gateway")

    device = await get_device_by_id(device_id, DB_PATH)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        await knx.read_value(device.group_address)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"status": "read_requested", "group_address": device.group_address}


@app.post("/api/import/ets")
async def import_ets(file: UploadFile):
    if not file.filename.endswith(".knxproj"):
        raise HTTPException(status_code=400, detail="File must be a .knxproj")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50 MB limit
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    try:
        devices = parse_knxproj(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    imported = 0
    for d in devices:
        await upsert_auto_device(d, DB_PATH)
        imported += 1

    all_devices = await get_all_devices(DB_PATH)
    await ws_manager.broadcast({
        "type": "full_refresh",
        "data": [dev.model_dump() for dev in all_devices],
    })

    return {"imported": imported, "total_devices": len(all_devices)}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial state
        devices = await get_all_devices(DB_PATH)
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {
                "devices": [d.model_dump() for d in devices],
                "connection": knx.status(),
            },
        }))

        # Keep alive – client may send ping
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if msg == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
