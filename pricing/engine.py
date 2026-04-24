"""
Apnamart Pricing Engine
=======================
Core SP calculation logic for FMCGF, FMCGNF, and Staples.
Takes product data dict → returns SP + remarks.

Usage:
    from pricing.engine import calculate_sp
    result = calculate_sp(product_dict)
"""

import math

# ── Margin-based discount table ──────────────────────────────────────────────
DISCOUNT_TABLE = [
    (0.10, 0.00),   # margin <= 10% → 0% discount
    (0.15, 0.02),   # margin <= 15% → 2%
    (0.20, 0.03),   # margin <= 20% → 3%
    (0.25, 0.05),   # margin <= 25% → 5%
    (0.30, 0.07),   # margin <= 30% → 7%
    (0.40, 0.10),   # margin <= 40% → 10%
    (0.54, 0.20),   # margin <= 54% → 20%
    (float('inf'), 0.50),  # margin > 54% → 50%
]


def get_discount_pct(margin: float) -> float:
    """Look up discount % from margin-based table."""
    for threshold, discount in DISCOUNT_TABLE:
        if margin <= threshold:
            return discount
    return 0.50


def safe_float(val, default=0.0) -> float:
    """Convert to float safely, handling None/empty/string."""
    if val is None or val == '' or val == 'NA':
        return default
    try:
        if isinstance(val, str):
            val = val.replace(',', '').replace('%', '').strip()
        return float(val)
    except (ValueError, TypeError):
        return default


def calculate_sp(product: dict) -> dict:
    """
    Calculate SP for a single product.

    Input product dict keys:
        item_code, display_name, master_category (FMCGF/FMCGNF/STPLS)
        kvi_tag: "KVI" / "NON KVI" / "Super KVI"
        mrp: float
        latest_inward_cost: float
        map_price: float (MAP — Minimum Advertised Price)
        off_invoice_pct: float (0-1, e.g., 0.10 for 10%)
        off_invoice_value: float (Rs.)
        on_invoice_pct: float (0-1)
        on_invoice_value: float (Rs.)
        is_excluded: bool
        exclusion_type: str (e.g., "BOGO", "baby_food")
        benchmark_sp: float (MAX of Blinkit SP, JioMart SP — online)
        benchmark_mrp: float (competitor MRP for reference)
        # Staples-specific:
        sku_type: "GKM" / "cost_based" (default "GKM")
        guardrail_lower: float (0-1, e.g., 0.20)
        guardrail_upper: float (0-1, e.g., 0.30)
        cost_based_markup: float (0-1, for cost-based Staples SKUs)
        city_sp_override: float (city-level SP if applicable)

    Returns dict:
        sp: float (final selling price)
        discount_pct: float
        retention_margin: float
        remarks: list[str]
        flags: list[str] (warnings/escalation flags)
        rule_applied: str
    """
    # ── Extract inputs ───────────────────────────────────────────────────
    mrp = safe_float(product.get('mrp'))
    inward_cost = safe_float(product.get('latest_inward_cost'))
    map_price = safe_float(product.get('map_price'))
    kvi_tag = (product.get('kvi_tag') or 'NON KVI').upper().strip()
    master_cat = (product.get('master_category') or '').upper().strip()
    is_excluded = product.get('is_excluded', False)
    exclusion_type = product.get('exclusion_type', '')
    benchmark_sp = safe_float(product.get('benchmark_sp'))
    sku_type = (product.get('sku_type') or 'GKM').upper().strip()

    # ── Promo values ─────────────────────────────────────────────────────
    off_inv_pct = safe_float(product.get('off_invoice_pct'))
    off_inv_val = safe_float(product.get('off_invoice_value'))
    on_inv_pct = safe_float(product.get('on_invoice_pct'))
    on_inv_val = safe_float(product.get('on_invoice_value'))

    # Calculate off-invoice value from % if only % given
    if off_inv_val == 0 and off_inv_pct > 0 and mrp > 0:
        off_inv_val = mrp * off_inv_pct

    # Calculate on-invoice value from % if only % given
    if on_inv_val == 0 and on_inv_pct > 0 and mrp > 0:
        on_inv_val = mrp * on_inv_pct

    # ── Rule 11: Dual invoice → pick the greater one ─────────────────────
    final_invoice_value = max(off_inv_val, on_inv_val)
    promo_source = 'off_invoice' if off_inv_val >= on_inv_val else 'on_invoice'
    has_promo = final_invoice_value > 0

    # ── Cost calculation ─────────────────────────────────────────────────
    # Effective cost base = MAP if available, else latest inward
    cost_base = map_price if map_price > 0 else inward_cost

    # Off-invoice adjusted cost (cost reduced by off-invoice promo)
    off_inv_adjusted_cost = cost_base - off_inv_val if off_inv_val > 0 else cost_base

    # For pricing rules, "cost" = off-invoice adjusted cost
    cost = off_inv_adjusted_cost

    # ── Margin calculation ───────────────────────────────────────────────
    margin = (mrp - cost) / mrp if mrp > 0 else 0
    grn_margin = (mrp - inward_cost) / mrp if mrp > 0 and inward_cost > 0 else 0

    # ── Result tracking ──────────────────────────────────────────────────
    remarks = []
    flags = []
    sp = mrp  # default: sell at MRP
    rule_applied = ''

    # ══════════════════════════════════════════════════════════════════════
    # STAPLES COST-BASED SKUs (separate flow)
    # ══════════════════════════════════════════════════════════════════════
    if master_cat == 'STPLS' and sku_type == 'COST_BASED':
        markup = safe_float(product.get('cost_based_markup'))
        if markup > 0:
            sp = cost * (1 + markup)
        else:
            # No markup defined — use current SP or cost + default
            sp = safe_float(product.get('current_sp')) or cost * 1.10
        remarks.append('Cost-based SKU, SP = cost + markup')
        rule_applied = 'STAPLES_COST_BASED'

        # City override
        city_override = safe_float(product.get('city_sp_override'))
        if city_override > 0:
            sp = city_override
            remarks.append(f'City SP override applied: {city_override}')

        # Guardrail check
        sp, guardrail_remarks = _check_guardrails(product, sp, mrp, cost)
        remarks.extend(guardrail_remarks)

        sp = _round_sp(sp)
        return _build_result(sp, mrp, cost, off_inv_adjusted_cost, margin,
                             grn_margin, final_invoice_value, promo_source,
                             remarks, flags, rule_applied)

    # ══════════════════════════════════════════════════════════════════════
    # FMCG + STAPLES GKM FLOW (Rules 1-11)
    # ══════════════════════════════════════════════════════════════════════

    # ── Rule 8: Exclusions (FMCGF only) ─────────────────────────────────
    if is_excluded:
        if has_promo:
            sp = mrp - final_invoice_value
            remarks.append(f'Excluded ({exclusion_type}), promo passed')
            rule_applied = 'RULE_8_EXCLUDED_WITH_PROMO'
        else:
            sp = mrp
            remarks.append(f'Excluded ({exclusion_type}), 0% discount')
            rule_applied = 'RULE_8_EXCLUDED_NO_PROMO'
        sp = max(sp, cost)  # cost floor
        sp = _round_sp(sp)
        return _build_result(sp, mrp, cost, off_inv_adjusted_cost, margin,
                             grn_margin, final_invoice_value, promo_source,
                             remarks, flags, rule_applied)

    # ── Rule 9: On-invoice danger check ──────────────────────────────────
    if on_inv_val > 0 and margin > 0:
        on_inv_margin_ratio = on_inv_val / (mrp * margin) if mrp * margin > 0 else 0
        if on_inv_margin_ratio > 0.80:
            # Check RM after applying on-invoice
            potential_sp = mrp - on_inv_val
            potential_rm = (potential_sp - cost) / potential_sp if potential_sp > 0 else 0
            if potential_rm < 0.07:  # RM < 6-7%
                flags.append(f'⚠️ On-invoice {on_inv_val} is {on_inv_margin_ratio:.0%} of margin. '
                             f'RM would be {potential_rm:.1%}. Escalate to Category Lead.')
                # Don't pass on-invoice — treat as if no on-invoice
                if promo_source == 'on_invoice':
                    final_invoice_value = off_inv_val
                    promo_source = 'off_invoice' if off_inv_val > 0 else 'none'
                    has_promo = final_invoice_value > 0
                    remarks.append('On-invoice removed (>80% margin, low RM)')

    # ── Rule 1: MRP <= 40 ───────────────────────────────────────────────
    if mrp <= 40:
        if has_promo:
            sp = mrp - final_invoice_value
            remarks.append(f'MRP<=40, promo passed ({promo_source}: {final_invoice_value})')
            rule_applied = 'RULE_1_PROMO'
        else:
            sp = mrp
            remarks.append('MRP<=40, no promo, SP=MRP')
            rule_applied = 'RULE_1_NO_PROMO'

    # ── Rule 2: NON KVI, MRP > 40 ───────────────────────────────────────
    elif kvi_tag == 'NON KVI' and mrp > 40:
        if has_promo:
            # Rule 2A: Promo available
            sp = mrp - final_invoice_value
            remarks.append(f'NON KVI, promo passed ({promo_source}: {final_invoice_value})')
            rule_applied = 'RULE_2A_NONKVI_PROMO'
        else:
            # Rule 2B: No promo → discount formula
            discount_pct = get_discount_pct(margin)
            sp = mrp * (1 - discount_pct)
            remarks.append(f'NON KVI, no promo, margin={margin:.1%}, discount={discount_pct:.0%}')
            rule_applied = 'RULE_2B_NONKVI_FORMULA'

    # ── Rule 3: KVI (or Super KVI), MRP > 40 ────────────────────────────
    elif kvi_tag in ('KVI', 'SUPER KVI') and mrp > 40:
        has_benchmark = benchmark_sp > 0

        if has_promo and has_benchmark:
            # Rule 3A: Promo + Benchmark
            promo_price = mrp - final_invoice_value
            sp = min(promo_price, benchmark_sp)
            # Cost floor
            if sp < cost:
                sp = cost
                remarks.append('Cost floor applied (MIN < cost)')
            remarks.append(f'KVI, promo+BM, promo_price={promo_price:.0f}, '
                           f'benchmark={benchmark_sp:.0f}, SP={sp:.0f}')
            rule_applied = 'RULE_3A_KVI_PROMO_BM'

        elif has_promo and not has_benchmark:
            # Rule 3B: Only Promo
            sp = mrp - final_invoice_value
            remarks.append(f'KVI, only promo ({promo_source}: {final_invoice_value})')
            rule_applied = 'RULE_3B_KVI_PROMO_ONLY'

        elif not has_promo and has_benchmark:
            # Rule 3C: Only Benchmark
            if benchmark_sp >= cost:
                sp = benchmark_sp
            else:
                sp = cost
                remarks.append('Benchmark < cost, SP=cost (0% retention)')
            remarks.append(f'KVI, only BM, benchmark={benchmark_sp:.0f}')
            rule_applied = 'RULE_3C_KVI_BM_ONLY'

        else:
            # Rule 3D: Neither
            discount_pct = get_discount_pct(margin)
            sp = mrp * (1 - discount_pct)
            remarks.append(f'KVI, no promo/BM, margin={margin:.1%}, discount={discount_pct:.0%}')
            rule_applied = 'RULE_3D_KVI_FORMULA'

    else:
        # Fallback (shouldn't happen normally)
        if has_promo:
            sp = mrp - final_invoice_value
            remarks.append(f'Fallback, promo passed')
        else:
            discount_pct = get_discount_pct(margin)
            sp = mrp * (1 - discount_pct)
            remarks.append(f'Fallback, discount formula applied')
        rule_applied = 'FALLBACK'

    # ══════════════════════════════════════════════════════════════════════
    # POST-CHECKS (apply to all)
    # ══════════════════════════════════════════════════════════════════════

    # ── Rule 7: High margin override (margin > 54%, MRP > 10) ────────────
    if mrp > 10 and margin > 0.54:
        high_margin_sp = mrp * 0.50
        # Exception: if promo gives more than 50% discount, use promo
        if has_promo:
            promo_sp = mrp - final_invoice_value
            promo_discount = (mrp - promo_sp) / mrp if mrp > 0 else 0
            if promo_discount > 0.50:
                # Promo is deeper than 50%, keep promo
                if sp > promo_sp:
                    sp = promo_sp
                remarks.append(f'High margin ({margin:.0%}), promo > 50% — promo kept')
            else:
                sp = high_margin_sp
                remarks.append(f'High margin override ({margin:.0%} > 54%), 50% discount applied')
                rule_applied = 'RULE_7_HIGH_MARGIN'
        else:
            sp = high_margin_sp
            remarks.append(f'High margin override ({margin:.0%} > 54%), 50% discount applied')
            rule_applied = 'RULE_7_HIGH_MARGIN'

    # ── Rule 4: SP = MRP minimum discount ────────────────────────────────
    if abs(sp - mrp) < 0.01 and mrp > 40:  # SP effectively equals MRP
        if mrp >= 200:
            min_discount = 0.015
            sp = mrp * (1 - min_discount)
            remarks.append('SP=MRP, MRP>=200 → 1.5% min discount')
            rule_applied = rule_applied or 'RULE_4_MIN_DISCOUNT'
        elif mrp >= 100:
            min_discount = 0.01
            sp = mrp * (1 - min_discount)
            remarks.append('SP=MRP, 100<=MRP<200 → 1% min discount')
            rule_applied = rule_applied or 'RULE_4_MIN_DISCOUNT'
        # MRP 40-100: no minimum discount, leave SP = MRP

    # ── Rule 6: Guardrails ───────────────────────────────────────────────
    # No negative discount
    if sp > mrp:
        sp = mrp
        remarks.append('Guardrail: SP > MRP, clamped to MRP')

    # SP >= cost (no loss)
    if sp < cost and cost > 0:
        flags.append(f'⚠️ SP ({sp:.0f}) < cost ({cost:.0f}), clamped to cost')
        sp = cost
        remarks.append('Guardrail: SP < cost, clamped to cost')

    # Check retention margin is not negative
    rm = (sp - cost) / sp if sp > 0 else 0
    if rm < 0:
        sp = cost
        remarks.append('Guardrail: negative RM, SP set to cost')

    # ── Staples-specific: guardrail margin bounds ────────────────────────
    if master_cat == 'STPLS' and sku_type != 'COST_BASED':
        sp, guardrail_remarks = _check_guardrails(product, sp, mrp, cost)
        remarks.extend(guardrail_remarks)

        # City-level override
        city_override = safe_float(product.get('city_sp_override'))
        if city_override > 0:
            sp = city_override
            remarks.append(f'City SP override: {city_override}')

    # ── Final rounding ───────────────────────────────────────────────────
    sp = _round_sp(sp)

    return _build_result(sp, mrp, cost, off_inv_adjusted_cost, margin,
                         grn_margin, final_invoice_value, promo_source,
                         remarks, flags, rule_applied)


def _check_guardrails(product: dict, sp: float, mrp: float, cost: float) -> tuple:
    """Check Staples guardrail margin thresholds. Returns (sp, remarks)."""
    remarks = []
    guardrail_lower = safe_float(product.get('guardrail_lower'))
    guardrail_upper = safe_float(product.get('guardrail_upper'))

    if guardrail_lower <= 0 and guardrail_upper <= 0:
        return sp, remarks

    # Current margin at this SP
    current_margin = (sp - cost) / sp if sp > 0 else 0

    if guardrail_lower > 0 and current_margin < guardrail_lower:
        remarks.append(f'Below guardrail lower ({current_margin:.1%} < {guardrail_lower:.0%})')
        # Note: breaches allowed under competitive pressure — flag but don't auto-fix
    if guardrail_upper > 0 and current_margin > guardrail_upper:
        remarks.append(f'Above guardrail upper ({current_margin:.1%} > {guardrail_upper:.0%})')

    return sp, remarks


def _round_sp(sp: float) -> float:
    """Round SP to nearest integer (standard practice)."""
    if sp <= 0:
        return 0
    return math.ceil(sp)  # Round up to nearest rupee


def _build_result(sp, mrp, cost, off_inv_adjusted_cost, margin, grn_margin,
                  final_invoice_value, promo_source, remarks, flags, rule_applied) -> dict:
    """Build the result dict."""
    discount_pct = (mrp - sp) / mrp if mrp > 0 else 0
    retention_margin = (sp - off_inv_adjusted_cost) / sp if sp > 0 else 0

    return {
        'sp': sp,
        'mrp': mrp,
        'cost': cost,
        'off_invoice_adjusted_cost': off_inv_adjusted_cost,
        'margin': margin,
        'grn_margin': grn_margin,
        'discount_pct': discount_pct,
        'retention_margin': retention_margin,
        'final_invoice_value': final_invoice_value,
        'promo_source': promo_source,
        'remarks': remarks,
        'flags': flags,
        'rule_applied': rule_applied,
        # Validation checks
        'sp_equals_mrp': abs(sp - mrp) < 0.01,
        'mrp_gte_sp': mrp >= sp,
        'sp_gte_cost': sp >= cost if cost > 0 else True,
    }


# ── Batch processing ─────────────────────────────────────────────────────────

def calculate_sp_batch(products: list[dict]) -> list[dict]:
    """Calculate SP for a list of products. Returns list of result dicts."""
    results = []
    for product in products:
        try:
            result = calculate_sp(product)
            result['item_code'] = product.get('item_code')
            result['display_name'] = product.get('display_name')
            result['kvi_tag'] = product.get('kvi_tag')
            result['master_category'] = product.get('master_category')
            results.append(result)
        except Exception as e:
            results.append({
                'item_code': product.get('item_code'),
                'display_name': product.get('display_name'),
                'error': str(e),
                'sp': 0,
                'remarks': [f'ERROR: {e}'],
                'flags': [f'⚠️ Calculation failed: {e}'],
            })
    return results


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Test cases from the real sheet data
    test_products = [
        # Example 1: MRP <= 40, with promo
        {
            'item_code': '13297', 'display_name': 'Bambino Dalia 400g',
            'master_category': 'STPLS', 'kvi_tag': 'NON KVI',
            'mrp': 35, 'latest_inward_cost': 27.3, 'map_price': 0,
            'off_invoice_value': 1.4, 'on_invoice_value': 0,
        },
        # Example 2: Non-KVI + on-invoice promo
        {
            'item_code': '8091', 'display_name': 'Patanjali Gonyle Floor Cleaner 1L',
            'master_category': 'FMCGNF', 'kvi_tag': 'NON KVI',
            'mrp': 75, 'latest_inward_cost': 62, 'map_price': 61.5,
            'off_invoice_value': 0, 'on_invoice_value': 3,
        },
        # Example 3: KVI + benchmark
        {
            'item_code': '104239', 'display_name': 'Almond Badaam Popular 500g',
            'master_category': 'STPLS', 'kvi_tag': 'KVI',
            'mrp': 539, 'latest_inward_cost': 370.50, 'map_price': 370.50,
            'off_invoice_value': 0, 'on_invoice_value': 0,
            'benchmark_sp': 429,
        },
        # Example 4: High margin override
        {
            'item_code': '97393', 'display_name': 'Basil Seeds 50g',
            'master_category': 'STPLS', 'kvi_tag': 'NON KVI',
            'mrp': 39, 'latest_inward_cost': 11, 'map_price': 0,
            'off_invoice_value': 0, 'on_invoice_value': 0,
        },
        # Example 5: KVI + promo + benchmark
        {
            'item_code': '2405', 'display_name': 'Aashirvaad Atta 5Kg',
            'master_category': 'STPLS', 'kvi_tag': 'Super KVI',
            'mrp': 283, 'latest_inward_cost': 216.612, 'map_price': 216.612,
            'off_invoice_value': 10, 'on_invoice_value': 0,
            'benchmark_sp': 235,
        },
        # Example 6: Excluded BOGO
        {
            'item_code': '97077', 'display_name': 'Savlon Hand Wash BOGO',
            'master_category': 'FMCGNF', 'kvi_tag': 'NON KVI',
            'mrp': 200, 'latest_inward_cost': 140, 'map_price': 140,
            'off_invoice_value': 0, 'on_invoice_value': 0,
            'is_excluded': True, 'exclusion_type': 'BOGO',
        },
        # Example 7: On-invoice danger check
        {
            'item_code': '73474', 'display_name': 'Horlicks Chocolate 1Kg',
            'master_category': 'FMCGF', 'kvi_tag': 'KVI',
            'mrp': 480, 'latest_inward_cost': 446.21, 'map_price': 446.21,
            'off_invoice_value': 0, 'on_invoice_value': 30,
        },
    ]

    print("=" * 80)
    print("PRICING ENGINE TEST RESULTS")
    print("=" * 80)

    for p in test_products:
        result = calculate_sp(p)
        print(f"\n{'─' * 60}")
        print(f"Product: {p['display_name']} ({p['item_code']})")
        print(f"  MRP={p['mrp']}, KVI={p.get('kvi_tag')}, Cat={p.get('master_category')}")
        print(f"  Cost={result['cost']:.2f}, Margin={result['margin']:.1%}")
        print(f"  ▸ SP = {result['sp']}")
        print(f"  ▸ Discount = {result['discount_pct']:.1%}")
        print(f"  ▸ RM = {result['retention_margin']:.1%}")
        print(f"  ▸ Rule: {result['rule_applied']}")
        print(f"  ▸ Remarks: {'; '.join(result['remarks'])}")
        if result.get('flags'):
            print(f"  ▸ FLAGS: {'; '.join(result['flags'])}")
        # Validation
        checks = []
        if not result.get('mrp_gte_sp', True):
            checks.append('FAIL: MRP < SP')
        if not result.get('sp_gte_cost', True):
            checks.append('FAIL: SP < cost')
        if checks:
            print(f"  ▸ VALIDATION: {', '.join(checks)}")
        else:
            print(f"  ▸ VALIDATION: All passed ✓")
