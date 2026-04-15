"""
Shared utilities for SAM pipeline scripts.
All common functions in ONE place — no more duplication.
"""
import math
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── String cleaning ─────────────────────────────────────────

def clean_str(v) -> str:
    """Return empty string for sentinel missing values (NA, nan, null, empty)."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none", "n/a", "#value!"):
        return ""
    return s


def normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


STOPWORDS = {"the", "and", "of", "a", "an", "with", "for", "in", "on", "to",
             "pack", "pc", "pcs", "n", "by", "free", "new"}


def tokens(s: str) -> set[str]:
    """Significant tokens (≥3 chars, not stopwords, not pure numbers)."""
    return {
        t for t in normalize(s).split()
        if len(t) >= 3 and t not in STOPWORDS and not t.isdigit()
    }


# ── Number parsing ──────────────────────────────────────────

def parse_num(v) -> float | None:
    """Parse numeric value from various formats (₹, Rs., commas, /-)."""
    if v is None or str(v).strip().lower() in ("", "na", "n/a", "nan", "null", "none", "#value!"):
        return None
    try:
        s = str(v).replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
        s = s.rstrip("/-").strip()
        val = float(s)
        if math.isinf(val) or val < 0:
            return None
        return val
    except (ValueError, TypeError):
        return None


# ── Unit parsing ────────────────────────────────────────────

UNIT_ALIASES = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "mls": "ml", "millilitre": "ml", "milliliter": "ml",
    "l": "l", "ltr": "l", "ltrs": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc", "n": "pc",
    "unit": "pc", "units": "pc", "pack": "pc",
}


def parse_unit(text: str) -> tuple[float | None, str | None]:
    """Parse unit string like '500 g', '2 x 100ml', '1/2 kg' into (value, normalized_unit)."""
    if not text:
        return None, None
    s = str(text).strip().lower()

    # Handle fractions: "1/2 kg" → "0.5 kg"
    s = re.sub(r"(\d+)/(\d+)", lambda m: str(round(int(m.group(1)) / int(m.group(2)), 4)), s)

    # Multipack: "N x M unit"
    m = re.search(r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|pieces|n|unit|units|pack)", s)
    if m:
        try:
            return float(m.group(1)) * float(m.group(2)), UNIT_ALIASES.get(m.group(3), m.group(3))
        except ValueError:
            pass

    # Single: "500 g"
    m = re.search(r"(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|pieces|n|unit|units|pack)\b", s)
    if m:
        try:
            return float(m.group(1)), UNIT_ALIASES.get(m.group(2), m.group(2))
        except ValueError:
            pass
    return None, None


def to_base_unit(value: float, unit: str) -> tuple[float, str]:
    """Convert to canonical base: g / ml / pc."""
    if unit == "kg":
        return value * 1000, "g"
    if unit == "l":
        return value * 1000, "ml"
    return value, unit


def units_compatible(u1: str, u2: str) -> bool:
    """True if two units are comparable (same base family)."""
    if not u1 or not u2:
        return False
    base1 = "g" if u1 in ("g", "kg") else ("ml" if u1 in ("ml", "l") else u1)
    base2 = "g" if u2 in ("g", "kg") else ("ml" if u2 in ("ml", "l") else u2)
    return base1 == base2


# ── File helpers ────────────────────────────────────────────

def latest_file(subdir: str, pattern: str) -> Path | None:
    """Find latest file matching glob pattern in data/<subdir>/."""
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


# ── Brand normalization ─────────────────────────────────────

BRAND_STOPWORDS = {"private", "limited", "ltd", "pvt", "company", "co", "the", "and"}

# TODO: populate from config/brand_aliases.json
BRAND_ALIASES = {
    "cdm": "cadbury dairy milk",
    "maggie": "maggi",
    "tata namak": "tata salt",
}


def normalize_brand(b: str) -> str:
    """Normalize brand name for matching."""
    if not b:
        return ""
    s = normalize(b)
    toks = [t for t in s.split() if t not in BRAND_STOPWORDS]
    result = " ".join(toks)
    return BRAND_ALIASES.get(result, result)
