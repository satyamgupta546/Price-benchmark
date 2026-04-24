# Apnamart Pricing Policy — Full Reference

Source: https://docs.google.com/document/d/1gdsPL33OaFV98I-HhYQ9ciY6jsrR8N7mP88DQkBHcNc/edit
Clarifications: Shashank Singh (author), 2026-04-15

---

## Core Definitions

| Term | Formula |
|------|---------|
| **Final Invoice Value** | Whichever promo (off-invoice OR on-invoice) is applicable. If both exist, apply the **higher** one. |
| **Off-invoice adjusted cost** | MAP − off-invoice value. If MAP unavailable → latest inward cost. If no off-invoice → adjusted cost = MAP (or latest inward cost). |
| **Margin** | (MRP − Off-invoice adjusted cost) / MRP |
| **Scan margin** | Margin *excluding* off-invoice |
| **Retention margin** | Margin *including* off-invoice |
| **GKM** | Gate Keeper Margin — for Staples GKM-based SKUs, Discount % derived from target retention-margin threshold + benchmark price |

---

## FMCG SP Rules (applied in order)

### Rule 1: MRP <= 40 (ALL SKUs)
```
SP = MRP − Final Invoice Value
If no promo → SP = MRP
```

### Rule 2: MRP > 40, Non-KVI
```
Case A: Promo available → SP = MRP − Final Invoice Value
Case B: No promo → Margin-based discount table:
```

| Margin Range | Discount % |
|-------------|------------|
| <= 10%      | 0%         |
| <= 15%      | 2%         |
| <= 20%      | 3%         |
| <= 25%      | 5%         |
| <= 30%      | 7%         |
| <= 40%      | 10%        |
| <= 54%      | 20%        |
| > 54%       | 50%        |

**Discount applied on MRP:** `SP = MRP × (1 − discount%)`

### Rule 3: MRP > 40, KVI
```
Case A: Promo + Benchmarking → SP = MIN(promo price, benchmarking price)
         Cost floor: if MIN < cost → SP = cost

Case B: Promo only → SP = MRP − Final Invoice Value

Case C: Benchmarking only → SP = benchmarking price
         If benchmarking < cost → SP = cost (0% retention, default)
         Conscious override allowed but baseline = zero retention

Case D: Neither → Margin-based discount table (same as Non-KVI)
```

---

## Edge Cases

### SP = MRP Minimum Discount (§3.1)
- MRP >= 200 → minimum 1.5% discount
- 100 <= MRP < 200 → minimum 1% discount
- 40 < MRP < 100 → **NO minimum discount, leave SP = MRP**

### SP = MRP because competitor is at MRP (§3.2)
Run margin-based formula. If margin is low (~7-8%) → formula yields 0% → SP stays at MRP. This is correct behavior.

### High Margin Override (§3.3)
- MRP > 10 AND margin > 54% → flat **50% discount** irrespective of promo
- Exception: if promo > 50%, apply promo instead (don't override downward)

### Exclusions (§5) — NO additional discounting
- Baby food
- BOGO kitted packs
- Chocolates with MRP < 80
- Instant-consumption drinks
- Packaged water
- **Chocolates MRP >= 80 follow standard FMCG rules**

---

## Guardrails (§4)

1. No negative discount; no negative retention margin — correct before execution
2. On-invoice promo > margin → **DO NOT pass**, flag to Category Lead
3. If on-invoice drops retention to 1-3% → escalate before executing
4. Dual invoice (on + off) → apply the **higher one only**
5. On-invoice > margin, pending decision → treat as if no on-invoice received

---

## Cost Floor Rules

| Scenario | Cost Floor? |
|----------|-------------|
| Non-KVI + off-invoice promo | Yes (pre-validated) |
| Non-KVI + on-invoice promo | Must validate. If on-invoice > margin → escalate |
| KVI + promo + benchmarking | Yes — clamp to cost |
| KVI + benchmarking only, bench < cost | SP = cost (0% retention) |

---

## Benchmarking Sources

| Type | Frequency | Sources | Notes |
|------|-----------|---------|-------|
| Monthly pricing file | Monthly | JioMart only | Generated after wholesale hafta |
| KVI daily benchmarking | Daily | Blinkit + JioMart | Don't be non-competitive vs either |
| Non-KVI benchmarking | Weekly | Blinkit + JioMart | 5% premium buffer allowed |
| Staples offline | Weekly | Reliance, DMart, Sumo Save | Drives Super KVI/KVI staples |
| Super KVI staples | Weekly (offline) | Reliance, DMart, Sumo Save | NOT daily |

**Benchmarking data source:** SAM scraped dashboard — MRP, SP, in-stock status for JioMart/Blinkit.

---

## KVI Classification

- **Staples:** Super KVI > KVI > Non-KVI (three tiers)
- **FMCG:** KVI vs Non-KVI (two tiers)
- Lists revised every few months — treat current pricing file's flag as ground truth

---

## Staples-Specific Rules (§8)

### SKU Types
1. **GKM-based:** Discount % on MRP (like FMCG)
2. **Cost-based:** SP = cost + markup (for loose/ASM SKUs). Markup varies per SKU. System back-calculates markup from given SP.

### Market-Linked
- Staples SP moves with market rates (e.g., edible oils)
- Each SKU has lower/upper retention-margin thresholds
- Breaches allowed when competitive pressure (lower) or market rate forces it (upper)

### City-Level Pricing
- No fixed trigger — judgment call
- Used selectively, typically higher than cluster-level SP to protect category margin

---

## Monthly Cadence

1. New pricing file generated monthly, executed right after wholesale hafta
2. Most promos in week 1; some in weeks 2-3
3. Staples promos go live only in first 2-3 days of the month

---

## Monthly Pricing File Links (April 2026)

- **FMCGF:** https://docs.google.com/spreadsheets/d/1W6NN-O8Kll3UkxQwMN2wWlCB68C3Qxjh8y5RK09FP8o/
- **FMCGNF:** https://docs.google.com/spreadsheets/d/1LJrFsn6g_QteziIBFsRhMR63W-S-gPTixNwdfMSrz_c/
- **STPLS:** https://docs.google.com/spreadsheets/d/15krKSrw9BHjWngD2tDJ9uCJh4PWPZ0o_bqMkM3FLmdg/
