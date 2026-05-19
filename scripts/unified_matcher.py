"""
Unified Matching Engine v2 — replaces cascade_match.py + stage3_match.py + compute_status.

Single-pass deterministic matcher with:
  - EAN fast-track bypass (barcode match → instant COMPLETE)
  - Advanced brand normalization with alias dictionary
  - Multipack-aware weight parsing ("Pack of 2 x 500g" → 1000g)
  - Packaging type detection (rigid vs soft → PARTIAL if mismatch)
  - Critical variant token checks (moong≠toor, dark≠milk → PARTIAL)
  - Token set ratio scoring (rapidfuzz, fallback to difflib)
  - Integrated COMPLETE/SEMI COMPLETE/PARTIAL/NA status computation

Usage (standalone — replaces cascade_match.py + stage3_match.py):
    python3 scripts/unified_matcher.py 834002 [blinkit|jiomart]

Usage (imported — in sam_daily_run.py):
    from unified_matcher import UnifiedMatchingEngine
    engine = UnifiedMatchingEngine(ean_map)
    engine.set_pool(sam_products)
    result = engine.match(am_product, am_mrp=mrp_value)
    status = engine.compute_status(am, am_mrp, sam_sp, sam_mrp, sam_name)
"""
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from utils import (
    clean_str, normalize, parse_num, tokens as util_tokens,
    UNIT_ALIASES, BRAND_STOPWORDS, to_base_unit,
    latest_file, PROJECT_ROOT,
)


# ── Fuzzy matching (rapidfuzz preferred, difflib fallback) ──

try:
    from rapidfuzz import fuzz as _rfuzz

    def _token_set_ratio(a: str, b: str) -> float:
        return _rfuzz.token_set_ratio(a, b)
except ImportError:
    def _token_set_ratio(a: str, b: str) -> float:
        """Fallback token set ratio using difflib."""
        a_sorted = " ".join(sorted(a.lower().split()))
        b_sorted = " ".join(sorted(b.lower().split()))
        return SequenceMatcher(None, a_sorted, b_sorted).ratio() * 100


# ── Result dataclass ──

@dataclass
class MatchResult:
    """Result of a single match attempt."""
    product: dict | None = None
    status: str = "NA"
    reason: str = ""
    score: float = 0.0
    flags: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
#  UnifiedMatchingEngine
# ══════════════════════════════════════════════════════════════════

class UnifiedMatchingEngine:
    """
    Single-pass deterministic product matcher.

    Replaces cascade_match.py + stage3_match.py with unified logic:
      1. EAN fast-track (barcode → instant COMPLETE)
      2. Brand → Weight → Packaging → Variant → Name → MRP cascade
      3. Integrated status computation (COMPLETE / SEMI COMPLETE / PARTIAL / NA)
    """

    # ── Brand alias dictionary (normalized form → canonical) ──
    BRAND_ALIASES = {
        # Ching's Secret
        "chings": "chings secret",
        "ching s": "chings secret",
        "ching s secret": "chings secret",
        # Maggi
        "maggie": "maggi",
        "maggii": "maggi",
        # Cadbury
        "cdm": "cadbury dairy milk",
        "cadbury": "cadbury",
        # Tata
        "tata namak": "tata salt",
        # Haldiram's
        "haldiram s": "haldirams",
        "haldiram": "haldirams",
        # Parle
        "parle g": "parle",
        # Nestle
        "nestle india": "nestle",
        # Britannia
        "britan": "britannia",
        # Dr. Oetker
        "dr oetker": "dr oetker",
        # HUL brands
        "hindustan unilever": "hul",
        "surf": "surf excel",
        # Patanjali
        "divya": "patanjali",
        # Godrej
        "godrej no1": "godrej no 1",
        # ITC
        "itc limited": "itc",
    }

    # ── Packaging type keywords ──
    RIGID_PACKAGING = frozenset({
        "jar", "tin", "bottle", "can", "container",
        "dabba", "pet", "glass", "tub", "bucket",
    })
    SOFT_PACKAGING = frozenset({
        "pouch", "refill", "sachet", "packet",
        "wrapper", "pillow", "standup", "poly",
    })

    # ── Critical variant groups ──
    # Within each group, AM moong ≠ SAM toor → PARTIAL (prevents cross-variant FP)
    VARIANT_GROUPS = [
        frozenset({"moong", "toor", "masoor", "chana", "urad",
                    "arhar", "rajma", "kabuli", "lobhia", "moth"}),
        frozenset({"dark", "milk", "white"}),                       # chocolate
        frozenset({"salted", "unsalted", "roasted", "raw"}),
        frozenset({"green", "black", "herbal", "masala"}),          # tea
        frozenset({"mustard", "sunflower", "groundnut", "soybean",
                    "olive", "coconut", "sesame", "kachi",
                    "refined", "filtered"}),                        # oil
        frozenset({"toned", "skimmed", "standardized", "fullcream"}),  # milk
        frozenset({"basmati", "kolam", "sona", "ponni", "gobindo"}),   # rice
        frozenset({"multigrain", "wholewheat", "maida",
                    "besan", "sooji", "ragi", "atta"}),             # flour
        frozenset({"red", "yellow", "kashmiri", "bydagi"}),         # chilli/spice
        frozenset({"iodized", "rock", "pink", "sendha"}),           # salt
    ]

    # ── Combo markers (skip these products entirely) ──
    COMBO_MARKERS = frozenset({"combo", "bundle", "assorted", "hamper", "gift"})

    # ── Thresholds ──
    NAME_SCORE_COMPLETE = 65.0      # token_set_ratio needed for COMPLETE eligibility
    NAME_SCORE_PARTIAL = 40.0       # below this → NA
    WEIGHT_EXACT_TOL = 0.001        # COMPLETE: weight must be exact (0.1% tolerance for float rounding)
    WEIGHT_SEMI_TOL = (0.9, 1.1)    # SEMI COMPLETE: ±10% weight tolerance
    MRP_EXACT_TOL = 0.01            # MRP exact match tolerance (₹)
    MRP_LOOSE_RATIO = (0.3, 3.0)    # MRP ratio bounds for SEMI COMPLETE
    PRICE_SANITY_MULT = 3.0         # SP > 3× AM MRP → reject

    # Unit regex shared across methods
    _UNIT_RE = (r'(g|gm|gms|gram|grams|kg|kgs|kilo|ml|mls|'
                r'l|ltr|ltrs|litre|liter|pc|pcs|piece|pieces|unit|units|n|nos)')

    def __init__(self, ean_map: dict | None = None):
        self.ean_map = ean_map or {}
        self._pool: list[dict] = []
        self._ean_index: dict[str, dict] = {}
        self._brand_index: dict[str, list[dict]] = defaultdict(list)

    # ══════════════════════════════════════════════════════════════
    #  Pool Setup (precompute indexes for fast matching)
    # ══════════════════════════════════════════════════════════════

    def set_pool(self, sam_products: list[dict]):
        """Set search pool and build indexes. Call once per city+platform."""
        self._pool = sam_products
        self._ean_index.clear()
        self._brand_index.clear()

        for p in sam_products:
            # Precompute normalized fields on each product dict
            p["_norm_brand"] = self._normalize_brand(p.get("brand") or "")
            p["_norm_name"] = normalize(p.get("product_name") or "")

            # Precompute base weight (avoids re-parsing per AM product)
            wt, unit = self._parse_weight(p.get("unit") or "")
            if wt is None:
                wt, unit = self._parse_weight(p.get("product_name") or "")
            p["_base_wt"] = wt
            p["_base_unit"] = unit

            # EAN index
            ean = str(p.get("barcode") or p.get("ean") or "").strip()
            if ean and len(ean) >= 8 and ean.isdigit():
                self._ean_index[ean] = p

            # Brand index
            if p["_norm_brand"]:
                self._brand_index[p["_norm_brand"]].append(p)

        print(f"[engine] Pool indexed: {len(sam_products)} products, "
              f"{len(self._ean_index)} EANs, "
              f"{len(self._brand_index)} brands", flush=True)

    # ══════════════════════════════════════════════════════════════
    #  Normalization Helpers
    # ══════════════════════════════════════════════════════════════

    def _normalize_brand(self, brand: str) -> str:
        """Normalize brand with stopword removal + alias resolution."""
        if not brand:
            return ""
        s = normalize(brand)
        toks = [t for t in s.split() if t not in BRAND_STOPWORDS]
        result = " ".join(toks)
        return self.BRAND_ALIASES.get(result, result)

    def _parse_weight(self, text: str) -> tuple[float | None, str | None]:
        """
        Advanced weight parser → (base_value, base_unit) in g/ml/pc.

        Handles multipacks:
          "500 g"              → (500.0, "g")
          "1.5 kg"             → (1500.0, "g")
          "2 x 500 g"         → (1000.0, "g")
          "500g x 2"          → (1000.0, "g")
          "Pack of 4 x 100ml" → (400.0, "ml")
          "Pack of 3"         → (3.0, "pc")
        """
        if not text:
            return None, None
        s = str(text).strip().lower()

        # Detect "pack of N" / "set of N" multiplier
        pack_n = 1
        pm = re.search(r'(?:pack|set|box)\s+(?:of\s+)?(\d+)', s)
        if pm:
            pack_n = int(pm.group(1))

        U = self._UNIT_RE

        # Pattern 1: N x M unit  ("2 x 500 g", "4x100ml")
        m = re.search(rf'(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*{U}\b', s)
        if m:
            v = float(m.group(1)) * float(m.group(2))
            u = UNIT_ALIASES.get(m.group(3), m.group(3))
            return to_base_unit(v, u)

        # Pattern 2: M unit x N  ("500g x 2", "1kg x 3")
        m = re.search(rf'(\d+\.?\d*)\s*{U}\s*[x×]\s*(\d+)', s)
        if m:
            v = float(m.group(1)) * int(m.group(3))
            u = UNIT_ALIASES.get(m.group(2), m.group(2))
            return to_base_unit(v, u)

        # Pattern 3: Simple M unit ("500 g", "1.5 kg") — apply pack_n multiplier
        m = re.search(rf'(\d+\.?\d*)\s*{U}\b', s)
        if m:
            v = float(m.group(1)) * pack_n
            u = UNIT_ALIASES.get(m.group(2), m.group(2))
            return to_base_unit(v, u)

        # "Pack of N" with no unit → count
        if pack_n > 1:
            return float(pack_n), "pc"

        return None, None

    def _detect_packaging(self, name: str) -> str | None:
        """Detect packaging type from product name: 'rigid', 'soft', or None."""
        words = set(normalize(name).split())
        if words & self.RIGID_PACKAGING:
            return "rigid"
        if words & self.SOFT_PACKAGING:
            return "soft"
        return None

    def _extract_variants(self, name: str) -> set[str]:
        """Extract critical variant tokens present in name."""
        words = set(normalize(name).split())
        found = set()
        for group in self.VARIANT_GROUPS:
            found |= (words & group)
        return found

    def _check_variant_conflict(self, am_vars: set[str], sam_vars: set[str]) -> bool:
        """True if products have conflicting variants from the same group.
        E.g., AM has 'moong' and SAM has 'toor' (both in dal group) → conflict."""
        for group in self.VARIANT_GROUPS:
            am_in = am_vars & group
            sam_in = sam_vars & group
            if am_in and sam_in and am_in != sam_in:
                return True
        return False

    def _is_loose_asm(self, am: dict) -> bool:
        """Check if AM product is a loose/ASM item in STPLS category."""
        name = (am.get("display_name") or "").lower()
        pt = (am.get("product_type") or "").upper()
        return (
            ("loose" in name or "asm" in name.split() or pt in ("LOOSE", "ASM"))
            and am.get("master_category") == "STPLS"
        )

    def _is_combo(self, name: str) -> bool:
        """Check if name indicates a combo/bundle product."""
        return bool(set(normalize(name).split()) & self.COMBO_MARKERS)

    @staticmethod
    def _unit_type_group(u: str | None) -> str | None:
        """Return unit family: 'weight', 'volume', 'count', or None."""
        if not u:
            return None
        u = str(u).lower().strip()
        if u in ("g", "gm", "gms", "kg", "kgs"):
            return "weight"
        if u in ("ml", "mls", "l", "ltr", "ltrs"):
            return "volume"
        if u in ("pc", "pcs", "piece", "pieces", "unit", "units", "n", "nos"):
            return "count"
        return None

    # ══════════════════════════════════════════════════════════════
    #  Core Matching — match()
    # ══════════════════════════════════════════════════════════════

    def match(self, am: dict, am_mrp: float | None = None) -> MatchResult:
        """
        Find best SAM match for one AM product. Single-pass algorithm.

        Args:
            am: AM product dict with keys: item_code, display_name, brand,
                product_type, unit, unit_value, mrp, master_category
            am_mrp: Override MRP from model 1808. Falls back to am["mrp"].

        Returns:
            MatchResult(product, status, reason, score, flags)
        """
        ic = str(am.get("item_code", ""))
        am_name = am.get("display_name") or ""
        am_brand = self._normalize_brand(am.get("brand") or "")
        am_unit_raw = (am.get("unit") or "").lower().strip()
        am_uv = parse_num(am.get("unit_value"))
        am_mrp_val = am_mrp if am_mrp is not None else parse_num(am.get("mrp"))
        is_loose = self._is_loose_asm(am)

        # Skip combo/bundle products
        if self._is_combo(am_name):
            return MatchResult(status="NA", reason="combo_product")

        # Parse AM base weight (unit_value+unit first, fallback to name)
        am_base_wt, am_base_unit = None, None
        if am_uv and am_unit_raw:
            u_norm = UNIT_ALIASES.get(am_unit_raw, am_unit_raw)
            am_base_wt, am_base_unit = to_base_unit(am_uv, u_norm)
        if am_base_wt is None:
            am_base_wt, am_base_unit = self._parse_weight(am_name)

        # ── STEP 1: EAN Fast-Track ──
        apna_ean = str(self.ean_map.get(ic, "")).strip()
        if apna_ean and len(apna_ean) >= 8 and apna_ean in self._ean_index:
            return MatchResult(
                product=self._ean_index[apna_ean],
                status="COMPLETE MATCH",
                reason="ean_exact",
                score=1.0,
            )

        # ── STEP 2: Build candidate set ──
        # Path A: strict brand match (fast — uses brand index)
        candidates = list(self._brand_index.get(am_brand, []))

        # Path B: no brand hit → broaden to name/brand token overlap
        if not candidates:
            am_name_toks = util_tokens(am_name)
            am_brand_toks = util_tokens(am.get("brand") or "")
            for p in self._pool:
                p_all = (util_tokens(p.get("product_name") or "")
                         | util_tokens(p.get("brand") or ""))
                brand_ok = bool(am_brand_toks and (am_brand_toks & p_all))
                common = am_name_toks & p_all
                if brand_ok or len(common) >= 2:
                    # When brand known but doesn't match, require 3+ common tokens
                    if not brand_ok and am_brand_toks and len(common) < 3:
                        continue
                    candidates.append(p)

        if not candidates:
            return MatchResult(status="NA", reason="no_candidates")

        # ── STEP 3: Weight filter (uses precomputed _base_wt/_base_unit) ──
        # Allow ±10% through as candidates (SEMI range), exact check later for COMPLETE
        if am_base_wt and am_base_unit and am_base_wt > 0:
            weighted = []
            for p in candidates:
                p_wt = p.get("_base_wt")
                p_unit = p.get("_base_unit")
                if p_wt and p_unit == am_base_unit and p_wt > 0:
                    ratio = p_wt / am_base_wt
                    if self.WEIGHT_SEMI_TOL[0] <= ratio <= self.WEIGHT_SEMI_TOL[1]:
                        weighted.append((p, abs(1 - ratio)))
            if weighted:
                weighted.sort(key=lambda x: x[1])
                candidates = [p for p, _ in weighted]
            elif not is_loose:
                return MatchResult(status="NA", reason="no_weight_match")

        # Loose items: check unit TYPE compatibility (kg↔g ok, kg↔ml not ok)
        if is_loose:
            am_type = (self._unit_type_group(am_base_unit)
                       or self._unit_type_group(am_unit_raw))
            if am_type:
                compat = [p for p in candidates
                          if not self._unit_type_group(p.get("_base_unit"))
                          or self._unit_type_group(p.get("_base_unit")) == am_type]
                if compat:
                    candidates = compat

        # ── STEP 4: Score each candidate ──
        am_name_norm = normalize(am_name)
        am_variants = self._extract_variants(am_name)
        am_pkg = self._detect_packaging(am_name)

        scored: list[tuple[dict, float, list[str]]] = []
        for p in candidates:
            p_name_norm = p.get("_norm_name", "")
            if not p_name_norm:
                continue

            # Skip SAM combos
            if self._is_combo(p.get("product_name") or ""):
                continue

            flags: list[str] = []

            # Packaging check (jar vs pouch → flag)
            p_pkg = self._detect_packaging(p.get("product_name") or "")
            if am_pkg and p_pkg and am_pkg != p_pkg:
                flags.append("packaging_mismatch")

            # Critical variant check (moong vs toor → flag)
            p_variants = self._extract_variants(p.get("product_name") or "")
            if self._check_variant_conflict(am_variants, p_variants):
                flags.append("variant_mismatch")

            # EAN cross-check (if both have barcodes, they MUST match)
            if apna_ean and len(apna_ean) >= 8:
                sam_ean = str(p.get("barcode") or p.get("ean") or "").strip()
                if sam_ean and len(sam_ean) >= 8 and apna_ean != sam_ean:
                    continue  # Confirmed different product — skip entirely

            # Name score (token set ratio, 0-100)
            name_score = _token_set_ratio(am_name_norm, p_name_norm)
            scored.append((p, name_score, flags))

        if not scored:
            return MatchResult(status="NA", reason="all_filtered")

        # Pick best by name score
        scored.sort(key=lambda x: -x[1])
        best_product, best_score, best_flags = scored[0]
        score_01 = best_score / 100.0

        # ── STEP 5: Determine status ──
        sam_mrp = parse_num(best_product.get("mrp"))
        sam_sp = (parse_num(best_product.get("price"))
                  or parse_num(best_product.get("sp")))

        # Price sanity: SP > 3× AM MRP → wrong product (combo/bulk)
        if sam_sp and am_mrp_val and sam_sp > am_mrp_val * self.PRICE_SANITY_MULT:
            return MatchResult(
                status="NA", reason="price_sanity_fail",
                score=score_01, flags=["price_too_high"],
            )

        has_block = ("packaging_mismatch" in best_flags
                     or "variant_mismatch" in best_flags)

        # ── SEMI COMPLETE path (loose/ASM in STPLS) ──
        if is_loose:
            if best_score < self.NAME_SCORE_PARTIAL:
                return MatchResult(
                    status="NA", reason="loose_low_score",
                    score=score_01, flags=best_flags,
                )
            # MRP sanity (reject if 3x off — clearly wrong product)
            if am_mrp_val and sam_mrp:
                try:
                    r = float(sam_mrp) / float(am_mrp_val) if float(am_mrp_val) > 0 else 0
                    if r < self.MRP_LOOSE_RATIO[0] or r > self.MRP_LOOSE_RATIO[1]:
                        return MatchResult(
                            best_product, "PARTIAL MATCH",
                            "loose_mrp_extreme", score_01, best_flags,
                        )
                except (ValueError, TypeError):
                    pass
            # Keyword overlap check (dal↔dal, sugar↔sugar)
            am_words = set(am_name.lower().replace("-", " ").split())
            sam_words = set(
                (best_product.get("product_name") or "").lower().replace("-", " ").split()
            )
            skip = {"loose", "1kg", "1", "kg", "g", "ml", "l",
                     "pack", "of", "the", "-", "|", "asm"}
            am_key, sam_key = am_words - skip, sam_words - skip
            if am_key and sam_key and not (am_key & sam_key):
                return MatchResult(
                    best_product, "PARTIAL MATCH",
                    "loose_no_keyword", score_01, best_flags,
                )
            if has_block:
                return MatchResult(
                    best_product, "PARTIAL MATCH",
                    "loose_heuristic_block", score_01, best_flags,
                )
            return MatchResult(
                best_product, "SEMI COMPLETE MATCH",
                "loose_match", score_01, best_flags,
            )

        # ── Standard path (non-loose) ──

        # Heuristic block (packaging or variant mismatch) → max PARTIAL
        if has_block:
            if best_score >= self.NAME_SCORE_PARTIAL:
                return MatchResult(
                    best_product, "PARTIAL MATCH",
                    "heuristic_block", score_01, best_flags,
                )
            return MatchResult(
                status="NA", reason="heuristic_block_low_score",
                score=score_01, flags=best_flags,
            )

        # Score too low → NA
        if best_score < self.NAME_SCORE_PARTIAL:
            return MatchResult(
                status="NA", reason="name_score_too_low",
                score=score_01, flags=best_flags,
            )

        # Score below COMPLETE threshold → PARTIAL
        if best_score < self.NAME_SCORE_COMPLETE:
            return MatchResult(
                best_product, "PARTIAL MATCH",
                "low_name_score", score_01, best_flags,
            )

        # ── Weight: exact vs approximate ──
        weight_exact = False
        weight_semi = False
        p_wt = best_product.get("_base_wt")
        p_wu = best_product.get("_base_unit")
        if am_base_wt and p_wt and am_base_unit and p_wu and am_base_unit == p_wu:
            if am_base_wt > 0 and p_wt > 0:
                ratio = p_wt / am_base_wt
                weight_exact = abs(1 - ratio) <= self.WEIGHT_EXACT_TOL  # exact same
                weight_semi = self.WEIGHT_SEMI_TOL[0] <= ratio <= self.WEIGHT_SEMI_TOL[1]  # ±10%

        # ── MRP exact check ──
        mrp_exact = False
        if am_mrp_val and sam_mrp:
            try:
                mrp_exact = abs(float(am_mrp_val) - float(sam_mrp)) < self.MRP_EXACT_TOL
            except (ValueError, TypeError):
                pass

        # ── COMPLETE: exact weight + name ≥65 + exact MRP ──
        if weight_exact and mrp_exact:
            return MatchResult(
                best_product, "COMPLETE MATCH",
                "exact_weight_name_mrp", score_01, best_flags,
            )

        # ── SEMI COMPLETE: weight ±10% + name ≥65 (MRP can differ) ──
        if weight_semi and best_score >= self.NAME_SCORE_COMPLETE:
            return MatchResult(
                best_product, "SEMI COMPLETE MATCH",
                "semi_weight_name", score_01, best_flags,
            )

        return MatchResult(
            best_product, "PARTIAL MATCH",
            "no_weight_or_mrp", score_01, best_flags,
        )

    # ══════════════════════════════════════════════════════════════
    #  Standalone Status Computation (for PDP / pre-matched data)
    # ══════════════════════════════════════════════════════════════

    def compute_status(self, am: dict, am_mrp, sam_sp, sam_mrp, sam_name) -> str:
        """
        Compute match status for already-matched data (PDP results, etc.).
        Replaces the old compute_status() in sam_daily_run.py.

        Adds packaging + variant heuristic checks on top of core logic.

        Args:
            am: AM product dict
            am_mrp: AM MRP (from model 1808 or fallback)
            sam_sp: SAM selling price
            sam_mrp: SAM MRP
            sam_name: SAM product name
        """
        if sam_sp is None:
            return "NA"

        am_name_str = am.get("display_name") or ""
        am_unit = (am.get("unit") or "").lower().strip()
        am_uv = am.get("unit_value")

        # ── Heuristic pre-checks (NEW — catches FPs the old logic missed) ──
        if sam_name:
            # Packaging mismatch → PARTIAL
            am_pkg = self._detect_packaging(am_name_str)
            sam_pkg = self._detect_packaging(sam_name)
            if am_pkg and sam_pkg and am_pkg != sam_pkg:
                return "PARTIAL MATCH"

            # Variant conflict → PARTIAL
            am_vars = self._extract_variants(am_name_str)
            sam_vars = self._extract_variants(sam_name)
            if self._check_variant_conflict(am_vars, sam_vars):
                return "PARTIAL MATCH"

        # ── SEMI COMPLETE (loose/ASM in STPLS) ──
        if self._is_loose_asm(am):
            am_ug = self._unit_type_group(am_unit)
            _, sam_wu = self._parse_weight(sam_name)
            sam_ug = self._unit_type_group(sam_wu)
            # Unit type must match (weight↔weight, volume↔volume)
            if am_ug and sam_ug and am_ug != sam_ug:
                return "PARTIAL MATCH"
            # MRP sanity (reject if ratio outside 0.3-3.0)
            if am_mrp and sam_mrp:
                try:
                    r = float(sam_mrp) / float(am_mrp) if float(am_mrp) > 0 else 0
                    if r < self.MRP_LOOSE_RATIO[0] or r > self.MRP_LOOSE_RATIO[1]:
                        return "PARTIAL MATCH"
                except (ValueError, TypeError):
                    pass
            # Keyword overlap (at least 1 meaningful word must match)
            if sam_name:
                am_words = set(am_name_str.lower().replace("-", " ").split())
                sam_words = set(sam_name.lower().replace("-", " ").split())
                skip = {"loose", "1kg", "1", "kg", "g", "ml", "l",
                         "pack", "of", "the", "-", "|", "asm"}
                am_key, sam_key = am_words - skip, sam_words - skip
                if am_key and sam_key and not (am_key & sam_key):
                    return "PARTIAL MATCH"
            return "SEMI COMPLETE MATCH"

        # ── Weight check ──
        sam_wt, sam_wu = self._parse_weight(sam_name)
        weight_exact = False
        weight_semi = False
        if am_uv and sam_wt and am_unit and sam_wu:
            try:
                u_norm = UNIT_ALIASES.get(am_unit, am_unit)
                am_bv, am_bu = to_base_unit(float(am_uv), u_norm)
                if am_bu == sam_wu and am_bv > 0 and sam_wt > 0:
                    ratio = sam_wt / am_bv
                    weight_exact = abs(1 - ratio) <= self.WEIGHT_EXACT_TOL
                    weight_semi = (self.WEIGHT_SEMI_TOL[0] <= ratio <= self.WEIGHT_SEMI_TOL[1])
                elif am_bu != sam_wu:
                    return "PARTIAL MATCH"  # Incompatible units
            except Exception:
                pass

        # ── MRP exact match ──
        mrp_match = False
        if am_mrp and sam_mrp:
            try:
                mrp_match = abs(float(am_mrp) - float(sam_mrp)) < self.MRP_EXACT_TOL
            except Exception:
                pass

        # COMPLETE: exact weight + exact MRP
        if weight_exact and mrp_match:
            return "COMPLETE MATCH"
        # SEMI COMPLETE: weight ±10% + name matched (MRP can differ)
        if weight_semi:
            return "SEMI COMPLETE MATCH"
        return "PARTIAL MATCH"

    # ══════════════════════════════════════════════════════════════
    #  Batch Matching
    # ══════════════════════════════════════════════════════════════

    def match_all(self, am_products: dict, mrp_map: dict | None = None) -> dict[str, MatchResult]:
        """
        Match all AM products against the pool.

        Args:
            am_products: {item_code: am_dict}
            mrp_map: {item_code: {"mrp": ...}} from model 1808

        Returns: {item_code: MatchResult}
        """
        results = {}
        mrp_map = mrp_map or {}
        valid_cats = {"STPLS", "FMCG", "FMCGF", "FMCGNF", "GM"}
        for ic, am in am_products.items():
            if am.get("master_category") not in valid_cats:
                continue
            mrp_rec = mrp_map.get(ic)
            am_mrp = parse_num(mrp_rec.get("mrp")) if mrp_rec else None
            results[ic] = self.match(am, am_mrp)
        return results


# ══════════════════════════════════════════════════════════════════
#  Pool Builder (consolidates duplicate logic from cascade/stage3)
# ══════════════════════════════════════════════════════════════════

def build_pool(pincode: str, platform: str) -> list[dict]:
    """Build SAM product search pool from BFS + category + jiomart master."""
    sam_products: list[dict] = []
    seen_pids: set[str] = set()

    # Source 1: BFS scrape data
    for p in sorted(
        (PROJECT_ROOT / "data" / "sam").glob(f"{platform}_{pincode}_*.json"),
        reverse=True,
    ):
        if "pdp" not in p.name and "category" not in p.name:
            data = json.load(open(p))
            for prod in data.get("products", []):
                pid = str(prod.get("product_id", ""))
                if pid and pid not in seen_pids:
                    seen_pids.add(pid)
                    sam_products.append(prod)
            break

    # Source 2: Category discovery
    for p in sorted(
        (PROJECT_ROOT / "data" / "sam").glob(f"{platform}_category_{pincode}_*.json"),
        reverse=True,
    ):
        cat = json.load(open(p))
        cat_added = 0
        for prod in cat.get("products", []):
            pid = str(prod.get("product_id") or prod.get("pid", ""))
            if pid and pid not in seen_pids:
                seen_pids.add(pid)
                sam_products.append({
                    "product_id": pid,
                    "product_url": prod.get(
                        "product_url",
                        f"https://blinkit.com/prn/x/prid/{pid}",
                    ),
                    "product_name": prod.get("name", ""),
                    "brand": ((prod.get("name") or "").split()[0]
                              if prod.get("name") else ""),
                    "price": prod.get("price") or prod.get("sp"),
                    "mrp": prod.get("mrp"),
                    "unit": prod.get("unit", ""),
                    "category": prod.get("category", ""),
                    "in_stock": bool(prod.get("inventory") or prod.get("stock")),
                })
                cat_added += 1
        print(f"[engine] Category products: {cat_added}")
        break

    # Source 3: Jiomart product master (permanent store)
    if platform == "jiomart":
        jm_path = PROJECT_ROOT / "data" / "jiomart_product_master.json"
        if jm_path.exists():
            jm = json.load(open(jm_path))
            jm_added = 0
            for pid, p in jm.items():
                if pid not in seen_pids and p.get("last_sp"):
                    seen_pids.add(pid)
                    sam_products.append({
                        "product_id": pid,
                        "product_url": p.get("url", ""),
                        "product_name": p.get("name", ""),
                        "brand": p.get("brand", ""),
                        "price": p.get("last_sp"),
                        "mrp": p.get("last_mrp"),
                        "unit": p.get("unit", ""),
                        "in_stock": p.get("in_stock", True),
                    })
                    jm_added += 1
            print(f"[engine] Jiomart master: {jm_added}")

    print(f"[engine] Total pool: {len(sam_products)}")
    return sam_products


# ══════════════════════════════════════════════════════════════════
#  Standalone Execution (replaces cascade_match.py + stage3_match.py)
# ══════════════════════════════════════════════════════════════════

def main(pincode: str, platform: str = "blinkit"):
    """Run unified matcher for a city+platform. Output is load_cascade compatible."""
    print(f"\n{'=' * 60}")
    print(f"  UNIFIED MATCHER — {platform} {pincode}")
    print(f"{'=' * 60}\n")

    # Load EAN map
    ean_map: dict = {}
    ean_path = PROJECT_ROOT / "data" / "ean_map.json"
    if ean_path.exists():
        ean_map = json.load(open(ean_path))
        print(f"[engine] EAN map: {len(ean_map)} barcodes")

    # Load AM product master
    am_path = PROJECT_ROOT / "data" / "am_product_master.json"
    if not am_path.exists():
        print("[engine] No AM product master — exiting")
        sys.exit(0)
    am_map = json.load(open(am_path))
    print(f"[engine] AM master: {len(am_map)} products")

    # Identify already-matched item_codes (from PDP stage)
    pdp_ok_codes: set[str] = set()
    pdp_files = sorted(
        (PROJECT_ROOT / "data" / "sam").glob(f"{platform}_pdp_{pincode}_*.json")
    )
    if pdp_files:
        pdp_data = json.load(open(pdp_files[-1]))
        pdp_ok_codes = {
            p["item_code"] for p in pdp_data.get("products", [])
            if p.get("status") == "ok" and p.get("item_code")
        }
        print(f"[engine] PDP ok: {len(pdp_ok_codes)} (skip)")

    # Build search pool
    sam_products = build_pool(pincode, platform)
    if not sam_products:
        print("[engine] No SAM products — exiting")
        sys.exit(0)

    # Init engine
    engine = UnifiedMatchingEngine(ean_map)
    engine.set_pool(sam_products)

    # Filter to unmatched AM products
    valid_cats = {"STPLS", "FMCG", "FMCGF", "FMCGNF", "GM"}
    unmatched_am = {
        ic: am for ic, am in am_map.items()
        if ic not in pdp_ok_codes
        and am.get("master_category") in valid_cats
    }
    print(f"[engine] Unmatched input: {len(unmatched_am)} products")

    # Load MRP data (warehouse-specific)
    cities_config = json.load(open(PROJECT_ROOT / "config" / "cities.json"))
    warehouse = cities_config["cities"].get(pincode, {}).get("warehouse", "WRHS_1")
    safe_wh = warehouse.lower().replace(" ", "_")
    mrp_path = PROJECT_ROOT / "data" / f"latest_mrp_{safe_wh}.json"
    mrp_map = json.load(open(mrp_path)) if mrp_path.exists() else {}
    print(f"[engine] MRP data: {len(mrp_map)} items ({warehouse})")

    # ── Run matching ──
    print(f"\n[engine] Matching {len(unmatched_am)} products...", flush=True)
    results = engine.match_all(unmatched_am, mrp_map)

    # ── Build output (load_cascade compatible format) ──
    matched: list[dict] = []
    unmatched_out: list[dict] = []
    status_counts: dict[str, int] = defaultdict(int)
    reason_counts: dict[str, int] = defaultdict(int)

    for ic, result in results.items():
        am = unmatched_am[ic]
        reason_counts[result.reason] += 1
        status_counts[result.status] += 1

        record: dict = {
            "item_code": ic,
            "am_name": am.get("display_name"),
            "am_brand": am.get("brand"),
            "am_product_type": am.get("product_type"),
            "am_weight": f"{am.get('unit_value', '')} {am.get('unit', '')}".strip(),
            "am_mrp": am.get("mrp"),
            "match_status": result.status,
            "match_reason": result.reason,
            "match_score": round(result.score, 3),
            "match_flags": result.flags,
        }

        if result.product:
            sam_sp = (parse_num(result.product.get("price"))
                      or parse_num(result.product.get("sp")))
            record.update({
                "sam_product_id": result.product.get("product_id"),
                "sam_product_url": result.product.get("product_url"),
                "sam_product_name": result.product.get("product_name"),
                "sam_brand": result.product.get("brand"),
                "sam_unit": result.product.get("unit"),
                "sam_price": sam_sp,
                "sam_mrp": result.product.get("mrp"),
                "sam_in_stock": result.product.get("in_stock", True),
            })
            matched.append(record)
        else:
            unmatched_out.append(record)

    # ── Print summary ──
    print(f"\n{'=' * 60}")
    print(f"  UNIFIED MATCH RESULT — {platform} {pincode}")
    print(f"{'=' * 60}")
    print(f"  Total processed:     {len(results)}")
    print(f"  Matched:             {len(matched)} "
          f"({len(matched) / max(len(results), 1) * 100:.1f}%)")
    print()
    print("  Status breakdown:")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"    {s:25s} {c}")
    print()
    print("  Reason breakdown:")
    for r, c in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"    {r:30s} {c}")

    if matched:
        print(f"\n  Top 5 matches (by score):")
        for m in sorted(matched, key=lambda x: -x["match_score"])[:5]:
            flags_str = (f" [{', '.join(m['match_flags'])}]"
                         if m["match_flags"] else "")
            print(f"    [{m['match_score']:.2f}] {m['am_name']}")
            print(f"           -> {m['sam_product_name']}{flags_str}")
            print(f"           SP {m['sam_price']} | MRP {m['sam_mrp']} "
                  f"| {m['match_status']}")

    # ── Save output (compatible with load_cascade) ──
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_unified_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "platform": platform,
            "compared_at": datetime.now().isoformat(),
            "engine_version": "unified_v2",
            "metrics": {
                "total_input": len(unmatched_am),
                "matched": len(matched),
                "unmatched": len(unmatched_out),
                "status_counts": dict(status_counts),
                "reason_counts": dict(reason_counts),
            },
            "new_mappings": matched,
            "unmatched": unmatched_out,
        }, f, indent=2, default=str)
    print(f"\n  Output: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
