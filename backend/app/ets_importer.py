"""
ETS project file (.knxproj) importer.

A .knxproj file is a ZIP archive containing XML files.
This parser extracts group addresses with their names and DPT types.
"""

import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Optional

from .categorizer import categorize_by_dpt
from .models import Device, DeviceCategory

logger = logging.getLogger(__name__)

# ETS XML namespace (varies by ETS version – we strip it)
_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def parse_knxproj(content: bytes) -> List[Device]:
    """
    Parse an ETS .knxproj file and return a list of Device objects.
    Raises ValueError on unreadable files.
    """
    devices: List[Device] = []

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # ETS stores the project data under 0.xml (or P-XXXX/0.xml)
            candidates = [
                n for n in zf.namelist()
                if n.endswith("0.xml") and "knx_master" not in n.lower()
            ]
            if not candidates:
                raise ValueError("No project XML found in .knxproj archive")

            for xml_name in candidates:
                with zf.open(xml_name) as fh:
                    try:
                        tree = ET.parse(fh)
                        devices.extend(_parse_tree(tree))
                    except ET.ParseError as exc:
                        logger.warning("Skipping %s: %s", xml_name, exc)

    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid .knxproj file: {exc}") from exc

    logger.info("ETS import: found %d group addresses", len(devices))
    return devices


# ── XML walking ───────────────────────────────────────────────────────────────

def _parse_tree(tree: ET.ElementTree) -> List[Device]:
    devices: List[Device] = []
    root = tree.getroot()

    for ga_elem in root.iter():
        if _strip_ns(ga_elem.tag) != "GroupAddress":
            continue

        raw_addr = ga_elem.get("Address")
        name = ga_elem.get("Name", "").strip() or "Unnamed"
        dpt_raw = ga_elem.get("DatapointType", "") or ga_elem.get("DPTs", "")

        if not raw_addr:
            continue

        try:
            addr = _decode_address(int(raw_addr))
        except (ValueError, TypeError):
            continue

        dpt = _normalise_dpt(dpt_raw)
        cat, dpt_name, unit = categorize_by_dpt(dpt, name)

        devices.append(
            Device(
                group_address=addr,
                name=name,
                category=cat,
                dpt=dpt,
                dpt_name=dpt_name,
                unit=unit,
                auto_detected=True,
            )
        )

    return devices


def _decode_address(raw: int) -> str:
    """Convert ETS integer address to three-level GA string (e.g. '1/2/3')."""
    main  = (raw >> 11) & 0x1F
    middle = (raw >> 8) & 0x07
    sub   = raw & 0xFF
    return f"{main}/{middle}/{sub}"


def _normalise_dpt(raw: str) -> Optional[str]:
    """
    ETS encodes DPTs as 'DPT-1', 'DPST-1-1', 'DPT-9', 'DPST-9-1', etc.
    Normalise to 'main.sub' format used by categorizer (e.g. '9.001').
    """
    if not raw:
        return None

    # DPST-9-1  →  9.001
    m = re.match(r"DPST-(\d+)-(\d+)", raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.{int(m.group(2)):03d}"

    # DPT-9  →  9 (no sub-type)
    m = re.match(r"DPT-(\d+)", raw, re.IGNORECASE)
    if m:
        return m.group(1)

    # Already in '9.001' format
    if re.match(r"^\d+\.\d+$", raw):
        parts = raw.split(".")
        return f"{parts[0]}.{int(parts[1]):03d}"

    return None
