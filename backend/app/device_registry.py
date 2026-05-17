"""
SQLite-backed device registry using aiosqlite.
All functions are async and accept an optional db_path override for testing.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import aiosqlite

from .models import Device, DeviceCategory, DeviceCreate, DeviceUpdate

logger = logging.getLogger(__name__)
DEFAULT_DB = "/app/data/knx_devices.db"


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_address  TEXT    UNIQUE NOT NULL,
    name           TEXT    NOT NULL,
    category       TEXT    NOT NULL DEFAULT 'unknown',
    dpt            TEXT,
    dpt_name       TEXT,
    value          TEXT,
    unit           TEXT,
    last_seen      TEXT,
    auto_detected  INTEGER NOT NULL DEFAULT 1,
    writable       INTEGER NOT NULL DEFAULT 1,
    readable       INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_CONFIG = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


async def init_db(db_path: str = DEFAULT_DB) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_DEVICES)
        await db.execute(_CREATE_CONFIG)
        await db.commit()
    logger.info("Database initialised at %s", db_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_device(row: aiosqlite.Row) -> Device:
    value: Any = None
    if row["value"]:
        try:
            value = json.loads(row["value"])
        except Exception:
            value = row["value"]
    return Device(
        id=row["id"],
        group_address=row["group_address"],
        name=row["name"],
        category=DeviceCategory(row["category"]),
        dpt=row["dpt"],
        dpt_name=row["dpt_name"],
        value=value,
        unit=row["unit"],
        last_seen=row["last_seen"],
        auto_detected=bool(row["auto_detected"]),
        writable=bool(row["writable"]),
        readable=bool(row["readable"]),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def get_all_devices(db_path: str = DEFAULT_DB) -> List[Device]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices ORDER BY category, group_address"
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_device(r) for r in rows]


async def get_devices_by_category(
    category: DeviceCategory, db_path: str = DEFAULT_DB
) -> List[Device]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE category = ? ORDER BY group_address",
            (category.value,),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_device(r) for r in rows]


async def get_device_by_address(
    group_address: str, db_path: str = DEFAULT_DB
) -> Optional[Device]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE group_address = ?", (group_address,)
        ) as cur:
            row = await cur.fetchone()
    return _row_to_device(row) if row else None


async def get_device_by_id(
    device_id: int, db_path: str = DEFAULT_DB
) -> Optional[Device]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ) as cur:
            row = await cur.fetchone()
    return _row_to_device(row) if row else None


async def upsert_auto_device(
    device: Device, db_path: str = DEFAULT_DB
) -> Device:
    """
    Insert or update a device discovered via bus monitoring.
    Manual overrides (name, category when auto_detected=0) are preserved.
    """
    async with aiosqlite.connect(db_path) as db:
        val_str = json.dumps(device.value) if device.value is not None else None
        await db.execute(
            """
            INSERT INTO devices
                (group_address, name, category, dpt, dpt_name, value, unit,
                 last_seen, auto_detected, writable, readable)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(group_address) DO UPDATE SET
                value     = excluded.value,
                last_seen = excluded.last_seen,
                dpt       = COALESCE(excluded.dpt, dpt),
                dpt_name  = COALESCE(excluded.dpt_name, dpt_name),
                unit      = COALESCE(excluded.unit, unit),
                -- Only overwrite category/name if still auto-managed
                category  = CASE WHEN auto_detected = 1
                                 THEN excluded.category
                                 ELSE category END,
                name      = CASE WHEN auto_detected = 1
                                 THEN excluded.name
                                 ELSE name END
            """,
            (
                device.group_address,
                device.name,
                device.category.value,
                device.dpt,
                device.dpt_name,
                val_str,
                device.unit,
                device.last_seen or _now(),
                1 if device.writable else 0,
                1 if device.readable else 0,
            ),
        )
        await db.commit()
    return await get_device_by_address(device.group_address, db_path)


async def create_device(
    payload: DeviceCreate, db_path: str = DEFAULT_DB
) -> Device:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO devices
                (group_address, name, category, dpt, writable, readable,
                 auto_detected, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                payload.group_address,
                payload.name,
                payload.category.value,
                payload.dpt,
                1 if payload.writable else 0,
                1 if payload.readable else 0,
                _now(),
            ),
        )
        await db.commit()
        device_id = cur.lastrowid
    return await get_device_by_id(device_id, db_path)


async def update_device(
    device_id: int, upd: DeviceUpdate, db_path: str = DEFAULT_DB
) -> Optional[Device]:
    fields: list[str] = []
    values: list[Any] = []

    if upd.name is not None:
        fields.append("name = ?")
        values.append(upd.name)
    if upd.category is not None:
        fields.append("category = ?")
        fields.append("auto_detected = 0")   # lock against auto-overwrite
        values.append(upd.category.value)
    if upd.dpt is not None:
        fields.append("dpt = ?")
        values.append(upd.dpt)
    if upd.writable is not None:
        fields.append("writable = ?")
        values.append(1 if upd.writable else 0)
    if upd.readable is not None:
        fields.append("readable = ?")
        values.append(1 if upd.readable else 0)

    if not fields:
        return await get_device_by_id(device_id, db_path)

    values.append(device_id)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE devices SET {', '.join(fields)} WHERE id = ?", values
        )
        await db.commit()
    return await get_device_by_id(device_id, db_path)


async def delete_device(device_id: int, db_path: str = DEFAULT_DB) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        await db.commit()
    return cur.rowcount > 0


async def update_device_value(
    group_address: str, value: Any, db_path: str = DEFAULT_DB
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE devices SET value = ?, last_seen = ? WHERE group_address = ?",
            (json.dumps(value), _now(), group_address),
        )
        await db.commit()


# ── Config store ──────────────────────────────────────────────────────────────

async def get_config(key: str, db_path: str = DEFAULT_DB) -> Optional[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def set_config(key: str, value: str, db_path: str = DEFAULT_DB) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()
