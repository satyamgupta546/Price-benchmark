# Apnamart Pricing — Simple Explanation

## Basics: Paisa Kahan Se Aata Hai

```
MRP = 100  (customer ko maximum price)
Cost = 70  (vendor se kitne mein kharida)
Margin = (MRP - Cost) / MRP = 30%  ← profit space
```

Vendor bolta hai: "Rs.10 extra de dunga off-invoice"
```
Adjusted Cost = 70 - 10 = 60
New Margin = (100 - 60) / 100 = 40%  ← zyada discount de sakte ho
```

---

## Key Terms

| Term | Meaning | Formula |
|------|---------|---------|
| **MRP** | Maximum Retail Price | Fixed by manufacturer |
| **MAP** | Minimum Advertised Price | Vendor sets this |
| **Cost** | What we pay | Off-invoice adjusted cost = MAP − off-invoice |
| **Margin** | Profit space | (MRP − Cost) / MRP |
| **Scan Margin** | Margin WITHOUT off-invoice | (MRP − MAP) / MRP |
| **Retention Margin (RM)** | Margin WITH off-invoice | (MRP − adjusted cost) / MRP |
| **SP BAU** | Selling Price (Business As Usual) | **THE OUTPUT — what customer pays** |
| **KVI** | Key Value Item | Price-sensitive products, must be competitive |
| **Non-KVI** | Non Key Value Item | Less price-sensitive, more margin |
| **GKM** | Gate Keeper Margin | Staples: target margin threshold |
| **Final Invoice Value** | Best promo available | Higher of on-invoice or off-invoice |

---

## 3 Types of Vendor Promos

| Type | Kya hai | Example |
|------|---------|---------|
| **Off-invoice** | Vendor directly paise deta hai per unit | "Rs.5 per unit de dunga" |
| **On-invoice** | Invoice pe discount milta hai | "Invoice pe 10% off" |
| **Dono hain?** | Jo ZYADA hai wo lo | Off=Rs.5, On=Rs.8 → use Rs.8 |

---

## FMCG Pricing Rules (FMCGF + FMCGNF — Same Rules)

### Rule 1: MRP <= 40 (ALL SKUs)
```
SP = MRP − Final Invoice Value
No promo? → SP = MRP

Example: Bambino Dalia 400g, MRP=35, Off-invoice=Rs.1.4
SP = 35 - 1.4 = 33.6
```

### Rule 2: MRP > 40, Non-KVI
```
Case A (Promo hai): SP = MRP − Final Invoice Value
Case B (No promo): Discount Formula → margin table se discount nikalo

Example: Patanjali Floor Cleaner, MRP=75, On-invoice=Rs.3, NON KVI
SP = 75 - 3 = 72
REMARK = "NON KVI, promo passed"
```

### Rule 3: MRP > 40, KVI (MOST COMPLEX)
```
Case A (Promo + Benchmark dono):
  SP = MIN(MRP − promo, benchmark price)
  But SP >= cost (COST FLOOR — loss nahi lenge)

Case B (Only Promo):
  SP = MRP − promo

Case C (Only Benchmark):
  SP = benchmark price
  If benchmark < cost → SP = cost (0% retention)

Case D (Neither):
  Discount Formula (same as Non-KVI)
```

### Margin-Based Discount Formula Table
```
Margin <= 10%  → 0% discount  (margin kam, discount mat do)
Margin <= 15%  → 2%
Margin <= 20%  → 3%
Margin <= 25%  → 5%
Margin <= 30%  → 7%
Margin <= 40%  → 10%
Margin <= 54%  → 20%
Margin > 54%   → 50%  (bahut margin hai → half price!)

SP = MRP × (1 − discount%)
```

### Rule 4: SP = MRP Minimum Discount
```
MRP >= 200    → minimum 1.5% discount dena padega
100 <= MRP < 200 → minimum 1% discount
40 < MRP < 100   → koi minimum nahi, MRP pe becho
```

### Rule 5: SP = MRP because competitor at MRP
```
KVI only, MRP > 40
Run discount formula. If result = 0% → SP stays at MRP. Correct.
```

### Rule 6: Guardrails
```
- No negative discount
- No negative retention margin
- MRP >= SP (SP kabhi MRP se zyada nahi)
- SP >= Cost (loss nahi lenge)
```

### Rule 7: High Margin Override
```
MRP > 10 AND margin > 54% → 50% discount STRAIGHT
Exception: agar promo > 50% hai → promo use karo (don't override downward)

Example: Basil Seeds, MRP=39, Cost=11, Margin=72%
SP = 39 × 0.50 = 19.5
```

### Rule 8: Exclusions (FMCGF ONLY)
```
Baby food, BOGO packs, chocolates < Rs.80, instant drinks, packaged water
→ 0% discount. Sirf promo pass karo agar hai.
Chocolates >= Rs.80 → normal rules
```

### Rule 9: On-Invoice Danger Check
```
On-invoice / Margin > 80%? → ⚠️ FLAG
If RM drops to 1-3% → Category Lead se baat karo
Don't pass this promo automatically
```

### Rule 10: Calculate Overall Retention Margin
```
RM = (MRP − SP) / MRP... nahi!
RM = (SP − adjusted cost) / SP... depends on definition

Actually: RM% is tracked as final output validation
```

### Rule 11: Dual Invoice → Pick Greater
```
Off-invoice = Rs.5, On-invoice = Rs.8
Final Invoice Value = Rs.8 (on-invoice wins)
```

---

## Decision Tree (Quick Reference)

```
START → Product aaya

1. Excluded hai? → YES → 0% discount (only pass promo if any) → DONE
2. MRP <= 40? → YES → SP = MRP - promo (or MRP) → DONE
3. KVI hai ya Non-KVI?
   ├── NON KVI:
   │   ├── Promo hai? → SP = MRP - promo → DONE
   │   └── No promo? → Discount formula (margin table) → DONE
   │
   └── KVI:
       ├── Promo + Benchmark → MIN(MRP-promo, benchmark), floor=cost → DONE
       ├── Only Promo → SP = MRP - promo → DONE
       ├── Only Benchmark → MAX(benchmark, cost) → DONE
       └── Neither → Discount formula → DONE

4. POST-CHECKS (apply to ALL above):
   ├── SP = MRP & MRP>=200? → minimum 1.5% discount
   ├── SP = MRP & 100<=MRP<200? → minimum 1% discount
   ├── Margin > 54% & MRP > 10? → 50% discount override
   ├── SP < cost? → SP = cost
   ├── SP > MRP? → SP = MRP
   └── On-invoice > 80% margin? → Flag ⚠️
```

---

## Staples — What's Different

| Feature | FMCG | Staples |
|---------|------|---------|
| KVI tiers | KVI / Non-KVI | Super KVI / KVI / Non-KVI |
| SKU types | All same | GKM-based + Cost-based |
| Guardrails | No | Yes (per-SKU upper/lower margin) |
| Benchmark sources | Online (Blinkit+Jio) | Online + Offline (Reliance, DMart, GT) |
| City pricing | No | Yes (city-level SP overrides) |
| Cost-based SKUs | No | SP = cost + markup (loose/ASM items) |

### Staples GKM-based SKUs
Same as FMCG rules, plus:
- Guardrail check: SP must keep margin within lower-upper bounds
- If benchmark pushes SP below guardrail lower → allowed (competitive pressure)
- If SP goes above guardrail upper → allowed (market rate change)

### Staples Cost-based SKUs (Loose/ASM)
```
SP = Cost + Markup%
Markup varies per SKU (system back-calculates from given SP)
Market-linked: SP moves with market rates (edible oils etc.)
```

### City-Level Pricing (Staples only)
```
Base SP = cluster-level (same for all cities in warehouse)
Override: some cities get different SP (usually higher)
Used selectively to protect category margin
```

---

## Benchmarking Sources

| What | Frequency | Source | Used For |
|------|-----------|--------|----------|
| Monthly pricing file | Monthly | JioMart only | FMCG monthly SP |
| KVI daily | Daily | Blinkit + JioMart (SAM data) | KVI SP adjustment |
| Non-KVI | Weekly | Blinkit + JioMart | 5% premium buffer |
| Staples offline | Weekly | Reliance, DMart, Sumo Save | Super KVI/KVI staples |
| Super KVI staples | Weekly | Offline stores | NOT daily |

---

## Monthly Cadence

1. New pricing file generated monthly, right after wholesale hafta
2. Most promos come in week 1; some in weeks 2-3
3. Staples promos: first 2-3 days of month only
4. KVI gets daily revision, Non-KVI gets weekly
5. KVI/Super KVI lists revised every few months

---

## Real Examples from Sheets

### Example 1: Simple (MRP <= 40)
```
Product: Bambino Dalia 400g (Staples)
MRP = 35, Off-invoice = Rs.1.4, Cost = 27.3
→ Rule 1: SP = 35 - 1.4 = 33.6 ✅
```

### Example 2: Non-KVI + Promo
```
Product: Patanjali Gonyle Floor Cleaner 1L (FMCGNF)
MRP = 75, On-invoice = Rs.3, NON KVI
→ Rule 2A: SP = 75 - 3 = 72
→ BAU Discount = 4%, RM = 14.58% ✅
```

### Example 3: Non-KVI + No Promo (Discount Formula)
```
Product: hypothetical, MRP = 200, Cost = 150, NON KVI, No promo
Margin = (200-150)/200 = 25%
→ Rule 2B: Table says 5% discount
→ SP = 200 × 0.95 = 190
```

### Example 4: KVI + Benchmark (Most Complex)
```
Product: Almond Badaam 500g (Staples, KVI)
MRP = 539, Cost = 370.50
Blinkit SP = 409, Jio SP = 429
Benchmark = MAX(409, 429) = 429
Promo = Rs.30

→ Rule 3A: 
  Promo price = 539 - 30 = 509
  SP = MIN(509, 429) = 429
  Cost floor: 429 > 370.50? YES ✅
  Final SP = 429
```

### Example 5: High Margin Override
```
Product: Basil Seeds 50g (Staples)
MRP = 39, Cost = 11, Margin = 72%
→ Rule 7: MRP > 10, Margin > 54%
→ 50% discount: SP = 39 × 0.5 = 19.5
```

### Example 6: On-Invoice Promo
```
Product: Horlicks 1Kg (FMCGF)
MRP = 480, GKM = 7.04%, On-invoice = Rs.30
Final Landing = 416.21

On-invoice % of margin = 30/33.79 = 88.8% → > 80%! ⚠️
→ Rule 9: Check RM. If RM < 6-7% → escalate to Category Lead
```

### Example 7: Off-Invoice Promo
```
Product: Rasna Fruit Fun 20g (FMCGF)
MRP = 47, Off-invoice = Rs.5, Cost = 37.6
Adjusted Cost = 37.6 - 5 = 32.6

MRP > 40, check KVI tag...
If NON KVI → Rule 2A: SP = 47 - 5 = 42
If KVI → Rule 3 (depends on benchmark availability)
```

### Example 8: Staples with Guardrails
```
Product: Almond Badaam 250g (Staples, cost-based, NON KVI)
MRP = 379, CP = 216, SP = 285
GM = 24%
Guardrail: 20% - 25%
Satellite: 25% - 30%

Current margin = (285-216)/285 = 24.2% → within 20-25% ✅
If SP drops to 260: margin = (260-216)/260 = 16.9% → BELOW 20% ⚠️
```

---

## What SAM Provides for Pricing

SAM daily scrape directly feeds into pricing decisions:

| SAM Output | Used In |
|------------|---------|
| Blinkit SP | KVI daily benchmarking, MAIN SHEET col 32 |
| JioMart SP | KVI daily benchmarking, MAIN SHEET col 33 |
| MAX(Blinkit, Jio) | Benchmark price for KVI Rule 3 |
| In-stock status | Only benchmark if competitor is in-stock |
| DMart SP | Staples offline comparison |
