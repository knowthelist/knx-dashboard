"""
DPT-based auto-categorisation of KNX group addresses.

Mapping:  dpt_string → (DeviceCategory, human_name, unit)

For ambiguous DPTs (1.001 switch, 5.001 percentage) the category is left as
UNKNOWN here and resolved by name-keyword matching in categorize_by_dpt().
"""

from typing import Any, Optional, Tuple
import struct


# ── Pure-Python KNX DPT 9 (2-byte float) codec ───────────────────────────────
# Avoids xknx API instability; DPT 9 is a custom KNX format, not IEEE 754.

def _dpt9_decode(b1: int, b2: int) -> float:
    """Decode two KNX DPT-9 bytes to a float."""
    sign = (b1 >> 7) & 1
    exp  = (b1 >> 3) & 0x0F
    mant = ((b1 & 0x07) << 8) | b2
    if sign:
        mant -= 2048          # two's complement for 11-bit mantissa
    return round(0.01 * mant * (1 << exp), 2)


def _dpt9_encode(value: float) -> list:
    """Encode a float to two KNX DPT-9 bytes."""
    sign = 0
    f = float(value)
    if f < 0:
        sign = 1
        f = -f
    mant = round(f * 100)
    exp  = 0
    while mant > 2047:
        mant = (mant + 1) >> 1
        exp += 1
    if sign:
        mant = (~mant + 1) & 0x7FF
    return [(sign << 7) | (exp << 3) | ((mant >> 8) & 0x07), mant & 0xFF]

from .models import DeviceCategory

# ── Name keyword tables ───────────────────────────────────────────────────────
# Lower-case keywords; first match wins.
_NAME_LIGHT = [
    "light", "lamp", "licht", "lampe", "leuchte", "dimm", "led",
    "spot", "bulb", "beleucht",
    # German KNX naming conventions
    "schalten",   # standard German KNX suffix for a light switch group address
    "einschalten", "ausschalten",
]
_NAME_BLIND = [
    "blind", "shutter", "jalousie", "rolladen", "rollo", "raffstore",
    "cover", "vorhang", "curtain", "markise",
]
_NAME_HEATING = [
    "heat", "temp", "heiz", "thermostat", "hvac", "klima", "setpoint",
    "soll", "cool", "boiler", "kessel",
]
_NAME_SPRINKLER = [
    "irrigat", "sprinkler", "bewässer", "bewaesser", "rasen", "garten",
    "lawn", "garden", "water", "wasser", "ventil terrasse", "ventil garten",
    "ventil rasen", "ventil außen", "ventil aussen",
]
_NAME_SENSOR = [
    "sensor", "measure", "detection", "binary", "move", "motion",
    "präsenz", "presence", "wind", "rain", "regen", "lux", "bright",
    "humid", "feucht", "co2", "smoke", "rauch", "alarm",
]
_NAME_MEDIA = [
    "sonos", "media", "audio", "musik", "music", "speaker", "lautsprecher",
    "radio", "player", "hifi", "hi-fi", "stereo", "amplifier", "verstaerker",
    "verstärker", "tv", "television", "volume", "lautstärke", "lautstaerke",
    "play", "pause", "mute", "stumm",
]


def _category_from_name(name: str) -> Optional[DeviceCategory]:
    """Return a category inferred purely from the device name, or None."""
    n = name.lower()
    # Sprinkler must be checked before heating ("ventil" is ambiguous)
    for kw in _NAME_SPRINKLER:
        if kw in n:
            return DeviceCategory.SPRINKLER
    for kw in _NAME_BLIND:
        if kw in n:
            return DeviceCategory.BLIND
    for kw in _NAME_HEATING:
        if kw in n:
            return DeviceCategory.HEATING
    for kw in _NAME_SENSOR:
        if kw in n:
            return DeviceCategory.SENSOR
    for kw in _NAME_LIGHT:
        if kw in n:
            return DeviceCategory.LIGHT
    for kw in _NAME_MEDIA:
        if kw in n:
            return DeviceCategory.MEDIA
    return None


# (category, human-readable name, unit)
_DPT_MAP: dict[str, Tuple[DeviceCategory, str, Optional[str]]] = {
    # ── 1.x  1-bit ────────────────────────────────────────────────────────────
    # 1.001 is intentionally UNKNOWN here — resolved by name below
    "1.001": (DeviceCategory.UNKNOWN, "Switch",      None),
    "1.002": (DeviceCategory.UNKNOWN, "Boolean",     None),
    "1.003": (DeviceCategory.UNKNOWN, "Enable",      None),
    "1.007": (DeviceCategory.UNKNOWN, "Step",        None),
    "1.008": (DeviceCategory.BLIND,   "Up / Down",   None),
    "1.009": (DeviceCategory.BLIND,   "Open / Close",None),
    "1.010": (DeviceCategory.UNKNOWN, "Start / Stop",None),
    # ── 3.x  4-bit relative control ───────────────────────────────────────────
    "3.007": (DeviceCategory.LIGHT,   "Dimming ctrl",None),
    "3.008": (DeviceCategory.BLIND,   "Blind ctrl",  None),
    # ── 5.x  1-byte unsigned ──────────────────────────────────────────────────
    # 5.001 / 5.004 are UNKNOWN — could be dim level or blind position → name decides
    "5.001": (DeviceCategory.UNKNOWN, "Percentage",  "%"),
    "5.003": (DeviceCategory.SENSOR,  "Angle",       "°"),
    "5.004": (DeviceCategory.UNKNOWN, "Percentage",  "%"),
    # ── 6.x  1-byte signed ────────────────────────────────────────────────────
    "6.001": (DeviceCategory.SENSOR,  "Relative value", "%"),
    # ── 7.x  2-byte unsigned ─────────────────────────────────────────────────
    "7.001": (DeviceCategory.SENSOR,  "Value",       None),
    "7.006": (DeviceCategory.SENSOR,  "Time (min)",  "min"),
    "7.007": (DeviceCategory.SENSOR,  "Time (h)",    "h"),
    "7.010": (DeviceCategory.SENSOR,  "Pulses",      None),
    "7.011": (DeviceCategory.SENSOR,  "Length",      "mm"),
    "7.012": (DeviceCategory.SENSOR,  "Current",     "mA"),
    # ── 8.x  2-byte signed ───────────────────────────────────────────────────
    "8.001": (DeviceCategory.SENSOR,  "Counter",     None),
    "8.002": (DeviceCategory.SENSOR,  "Time (ms)",   "ms"),
    # ── 9.x  2-byte float ────────────────────────────────────────────────────
    "9.001": (DeviceCategory.HEATING, "Temperature", "°C"),
    "9.002": (DeviceCategory.SENSOR,  "Temp. Diff.", "K"),
    "9.004": (DeviceCategory.SENSOR,  "Illuminance", "lux"),
    "9.005": (DeviceCategory.SENSOR,  "Wind speed",  "m/s"),
    "9.006": (DeviceCategory.SENSOR,  "Pressure",    "Pa"),
    "9.007": (DeviceCategory.SENSOR,  "Humidity",    "%"),
    "9.010": (DeviceCategory.SENSOR,  "Time",        "s"),
    "9.016": (DeviceCategory.SENSOR,  "Current",     "mA"),
    "9.020": (DeviceCategory.SENSOR,  "Voltage",     "mV"),
    "9.021": (DeviceCategory.SENSOR,  "Power",       "W"),
    # ── 14.x  4-byte float ───────────────────────────────────────────────────
    "14.019": (DeviceCategory.SENSOR, "Current",     "A"),
    "14.027": (DeviceCategory.SENSOR, "Power",       "W"),
    # ── 19.x  Date+Time ──────────────────────────────────────────────────────
    "19.001": (DeviceCategory.SENSOR, "DateTime",    None),
    # ── 17.x / 18.x  Scene ───────────────────────────────────────────────────
    "17.001": (DeviceCategory.UNKNOWN,"Scene",       None),
    "18.001": (DeviceCategory.UNKNOWN,"Scene",       None),
    # ── 20.x  HVAC ───────────────────────────────────────────────────────────
    "20.102": (DeviceCategory.HEATING,"HVAC Mode",   None),
    # ── 232.x  RGB colour ────────────────────────────────────────────────────
    "232.600":(DeviceCategory.LIGHT,  "RGB Colour",  None),
}


def categorize_by_dpt(
    dpt: Optional[str], name: Optional[str] = None
) -> Tuple[DeviceCategory, str, Optional[str]]:
    """
    Return (category, human_name, unit) for a DPT string like '9.001'.

    For ambiguous DPTs (e.g. 1.001 switch, 5.001 percentage) that map to
    UNKNOWN in _DPT_MAP, the device name is used as a secondary signal.
    """
    if not dpt:
        # No DPT at all — try name only
        cat = _category_from_name(name) if name else None
        return cat or DeviceCategory.UNKNOWN, "Unknown", None

    if dpt in _DPT_MAP:
        cat, dpt_name, unit = _DPT_MAP[dpt]
        # If DPT maps to UNKNOWN, refine with name keywords
        if cat == DeviceCategory.UNKNOWN and name:
            cat = _category_from_name(name) or DeviceCategory.UNKNOWN
        return cat, dpt_name, unit

    # Fallback on main type only — conservative: 1.x and 5.x stay UNKNOWN
    main = dpt.split(".")[0] if "." in dpt else dpt
    fallbacks: dict[str, Tuple[DeviceCategory, str, Optional[str]]] = {
        "1":  (DeviceCategory.UNKNOWN, "Switch",    None),
        "3":  (DeviceCategory.UNKNOWN, "Dimming",   None),
        "5":  (DeviceCategory.UNKNOWN, "Percentage","%"),
        "6":  (DeviceCategory.SENSOR,  "Signed",    None),
        "7":  (DeviceCategory.SENSOR,  "Value",     None),
        "8":  (DeviceCategory.SENSOR,  "Signed",    None),
        "9":  (DeviceCategory.SENSOR,  "Float",     None),
        "10": (DeviceCategory.SENSOR,  "Time",      None),
        "11": (DeviceCategory.SENSOR,  "Date",      None),
        "12": (DeviceCategory.SENSOR,  "Counter",   None),
        "13": (DeviceCategory.SENSOR,  "Counter",   None),
        "14": (DeviceCategory.SENSOR,  "Float 4B",  None),
        "19": (DeviceCategory.SENSOR,  "DateTime",  None),
        "20": (DeviceCategory.HEATING, "HVAC",      None),
    }
    cat, dpt_name, unit = fallbacks.get(main, (DeviceCategory.UNKNOWN, "Unknown", None))
    if cat == DeviceCategory.UNKNOWN and name:
        cat = _category_from_name(name) or DeviceCategory.UNKNOWN
    return cat, dpt_name, unit


def infer_dpt(raw_bytes: bytes) -> Optional[str]:
    """Best-effort DPT inference from raw telegram bytes (no DPT known yet)."""
    length = len(raw_bytes)
    if length == 0:
        return None   # genuinely unknown — don't force a category
    if length == 1:
        v = raw_bytes[0]
        if v <= 1:
            return "1.001"   # boolean switch (category resolved by name)
        if v <= 100:
            return "5.001"   # percentage (category resolved by name)
        return "5.004"
    if length == 2:
        # Try to interpret as a plausible DPT 9 value
        try:
            val = _dpt9_decode(raw_bytes[0], raw_bytes[1])
            if -10.0 <= val <= 80.0:
                return "9.001"
            if 0.0 <= val <= 100.0:
                return "9.007"
            return "9.001"
        except Exception:
            pass
    if length == 4:
        return "14.027"
    return None


def decode_raw(raw_bytes: bytes, dpt: Optional[str]) -> Tuple[Any, Optional[str]]:
    """Decode raw KNX bytes into a Python value. Returns (value, resolved_dpt)."""
    if not raw_bytes:
        return None, dpt

    resolved = dpt or infer_dpt(raw_bytes)

    try:
        main = int(resolved.split(".")[0]) if resolved else None

        if main == 1 or (resolved and resolved.startswith("1")):
            return bool(raw_bytes[0] & 0x01), resolved

        if main == 5:
            v = raw_bytes[0]
            if resolved == "5.001":
                return round(v * 100 / 255, 1), resolved
            return v, resolved

        if main == 6 and len(raw_bytes) == 1:
            # 1-byte signed
            return struct.unpack('>b', bytes(raw_bytes))[0], resolved

        if main == 7 and len(raw_bytes) == 2:
            # 2-byte unsigned integer
            return struct.unpack('>H', bytes(raw_bytes))[0], resolved

        if main == 8 and len(raw_bytes) == 2:
            # 2-byte signed integer
            return struct.unpack('>h', bytes(raw_bytes))[0], resolved

        if main == 9 and len(raw_bytes) == 2:
            return _dpt9_decode(raw_bytes[0], raw_bytes[1]), resolved

        if main == 10 and len(raw_bytes) == 3:
            # DPT 10 = time-of-day: byte0 = weekday<<5|hour, byte1 = min, byte2 = sec
            hour = raw_bytes[0] & 0x1F
            return '{:02d}:{:02d}:{:02d}'.format(hour, raw_bytes[1], raw_bytes[2]), resolved

        if main == 11 and len(raw_bytes) == 3:
            # DPT 11 = date: byte0 = day, byte1 = month, byte2 = year (0=2000, 90=1990)
            day, month, yr = raw_bytes[0], raw_bytes[1], raw_bytes[2]
            year = 2000 + yr if yr <= 99 else 1900 + yr
            return '{}-{:02d}-{:02d}'.format(year, month, day), resolved

        if main == 12 and len(raw_bytes) == 4:
            # 4-byte unsigned integer
            return struct.unpack('>I', bytes(raw_bytes))[0], resolved

        if main == 13 and len(raw_bytes) == 4:
            # 4-byte signed integer (e.g. energy in Wh)
            return struct.unpack('>i', bytes(raw_bytes))[0], resolved

        if main == 14 and len(raw_bytes) == 4:
            # DPT 14 = IEEE 754 single-precision big-endian
            return round(struct.unpack('>f', bytes(raw_bytes))[0], 3), resolved

        if main == 19 and len(raw_bytes) == 8:
            # DPT 19 = date+time: year offset from 1900, month, day, DoW|hour, min, sec
            year  = 1900 + raw_bytes[0]
            month = raw_bytes[1]
            day   = raw_bytes[2]
            hour  = raw_bytes[3] & 0x1F
            minute = raw_bytes[4]
            second = raw_bytes[5]
            return '{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
                year, month, day, hour, minute, second), resolved

    except Exception:
        pass

    # Fallback: return list of byte values
    return list(raw_bytes), resolved
