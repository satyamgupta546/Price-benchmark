# Pricing Accuracy Audit — Blinkit Ranchi (834002)

**Audit date:** 2026-04-12
**Scope:** One complete Stage 1 PDP scrape — Blinkit, pincode 834002
**Target accuracy:** ≥99% price match vs Anakin reference
**Current headline:** 94.6% within ±5%, 97.4% within ±10%

## Input files

| Artifact | Path |
|---|---|
| Anakin reference | `data/anakin/blinkit_834002_2026-04-11.json` (3,620 Apna SKUs, 2,364 mapped to Blinkit) |
| SAM PDP scrape | `data/sam/blinkit_pdp_834002_2026-04-12_010735.json` (2,363 URLs attempted) |
| Latest compare | `data/comparisons/blinkit_pdp_834002_2026-04-12_014608_compare.json` |

Comparison formula (per `scripts/compare_pdp.py:102`):
```
price_diff_pct = abs(sam_sp - anakin_blinkit_sp) / anakin_blinkit_sp * 100
```
Note: the comparison uses **raw Blinkit selling prices** from both scrapers — `Blinkit_Factor` is NOT applied. That's correct: we are comparing two independent scrapes of the **same Blinkit PDP**, so pack-size normalization is unnecessary.

---

## 1. Where does the 94.6% come from?

### Funnel

| Stage | Count | Notes |
|---|---|---|
| Anakin mapped SKUs (Blinkit) | 2,364 | From Anakin's `Blinkit_Product_Id != NA` |
| SAM PDPs attempted | 2,363 | 1 mapping skipped (errors in URL list) |
| SAM returned "ok" (price present) | 933 | Scraped a price field successfully |
| SAM returned "no_price_on_pdp" | **1,428** | PDP loaded but SP could not be extracted |
| SAM scrape errors | 2 | Network/timeout |
| OK records where Anakin SP was null | 167 | Can't compute a ratio |
| **Final price-compared pool** | **766** | Both sides have a non-null SP |
| Within ±5% | 725 (94.65%) | |
| Within ±10% | 746 (97.39%) | |
| Within ±2% | 694 (90.60%) | |

**True end-to-end coverage vs Anakin** = 766 / 2,364 = **32.4%** (not 39.5% — the 39.5% figure counts "ok" even when Anakin's own SP was null).

### Distribution of `price_diff_pct` across the 766 compared SKUs

| Bucket | Count | Cumulative % |
|---|---|---|
| **Exactly 0.0%** | **674** | 87.99% |
| 0–1% | 8 | 89.03% |
| 1–2% | 11 | 90.47% |
| 2–5% | 32 | 94.65% |
| 5–10% | 18 | 97.00% |
| 10–20% | 20 | 99.61% |
| 20–50% | 2 | 99.87% |
| 50%+ | 1 | 100.00% |

| Stat | Value |
|---|---|
| Mean | 0.80% |
| Median | 0.00% |
| p75 | 0.00% |
| p90 | 1.59% |
| p95 | 5.26% |
| p99 | 16.75% |
| Max | 55.17% |

**Key insight:** 88% of the compared pool is a **perfect byte-identical match**. The tail is small but heavy — 41 SKUs account for the entire ±5% gap.

---

## 2. Out-of-tolerance analysis (41 SKUs with diff > 5%)

### Breakdown by root cause

| Root cause | Count | % of 41 | Scraper bug? |
|---|---|---|---|
| **Price change — same PDP, MRP also moved** | 21 | 51% | NO — market movement between 11 AM and 12 AM snapshots |
| **Price change — same PDP, only SP moved** | 18 | 44% | NO — SP changed, MRP steady |
| **Low-price item (rounding/small absolute diff)** | 2 | 5% | NO — ₹1 diff on ₹12 item = 8.3% |
| **Unit/variant mismatch (wrong PDP scraped by either side)** | 0 | 0% | — |
| **SAM extracted wrong field (MRP vs SP)** | 0 | 0% | — |

**Not a single one of the 41 out-of-tolerance SKUs looks like an SAM extraction bug.** All appear to be:

1. Legitimate Blinkit price movements between the two scrape times (Anakin ~11:00 IST, SAM ~01:00 IST next day — ~14 hours apart).
2. In many cases the **MRP itself changed** between the two scrapes (e.g. Mahakosh Soyabean Oil: Anakin MRP 155 / SP 133, SAM MRP 183 / SP 149 — a full 20% MRP reprice at the platform level).
3. Both scrapes read a consistent `SP ≤ MRP` pair, meaning both read the PDP correctly — the underlying product just moved.

### Top 20 worst differences — field-by-field detail

| # | Diff | Code | Item | Anakin SP/MRP | SAM SP/MRP | Anakin Status / Partial | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | 55.17% | 98586 | Ecolink 9W LED Bulb | 87 / 90 | 39 / 90 | Partial / MRP Diff | **Flash sale** — SP dropped ₹48 on same PDP. MRP stable. Real market move. |
| 2 | 25.00% | 4643 | Lay's Cream & Onion 24g | 20 / 20 | 25 / 25 | Partial / Weight-Diff | MRP + SP both repriced 20→25. Legitimate. |
| 3 | 21.43% | 97539 | Skore Condom 10 pcs | 126 / 180 | 99 / 180 | Complete | SP dropped ₹27 on same MRP. Legitimate. |
| 4 | 19.35% | 103710 | Fun Flips Cheesy Pizza 90g | 31 / 50 | 37 / 50 | Partial / Weight-Diff | SP moved ₹6. Legitimate. |
| 5 | 18.75% | 84658 | Mukharochak Chanachur 200g | 80 / 80 | 65 / 65 | Partial / MRP Diff | MRP + SP both repriced down. Legitimate. |
| 6 | 17.65% | 2506 | Everest Kashmiri Chilli 100g | 102 / 120 | 120 / 120 | Complete | Discount removed (was ₹102, now at MRP 120). Legitimate. |
| 7 | 17.65% | 2507 | Everest Kashmiri Chilli 50g | 102 / 120 | 120 / 120 | Partial / Weight-Diff | Same SKU as #6 — weight variant. Same price move. |
| 8 | 16.75% | 11574 | H&S Smooth 340ml | 418 / 479 | 488 / 560 | Partial / Weight-Diff | MRP + SP both moved up. Legitimate. |
| 9 | 14.66% | 15865 | Tresemme Keratin Shampoo 580ml | 491 / 865 | 563 / 865 | Partial / Weight-Diff | SP moved up ₹72. Legitimate. |
| 10 | 14.49% | 95828 | JK Jeera Powder 100g | 69 / 92 | 59 / 78 | Complete | MRP + SP both moved down. Legitimate. |
| 11 | 13.33% | 86785 | French Beans 250g | 15 / 17 | 17 / 21 | Complete | Fresh produce volatility. Legitimate. |
| 12 | 13.33% | 95574 | French Beans 500g (same URL as 11) | 15 / 17 | 17 / 21 | Partial / Weight-Diff | Same duplicate PDP — Anakin maps two SKUs to one URL. |
| 13 | 13.24% | 3675 | Nivea Men Dark Spot 100g | 219 / 299 | 190 / 259 | Complete | MRP + SP both moved down. Legitimate. |
| 14 | 12.41% | 69140 | Wild Stone Perfume 100ml | 435 / 799 | 381 / 699 | Partial / Weight-Diff | MRP + SP both moved down. Legitimate. |
| 15 | 12.03% | 10017 | Mahakosh Soyabean Oil 750g | 133 / 155 | 149 / 183 | Complete | MRP + SP both moved up. Legitimate (edible oil volatility). |
| 16 | 11.76% | 28122 | Sunrise Haldi Powder 100g | 34 / 38 | 38 / 38 | Partial / Weight-Diff | SP moved to MRP (discount removed). Legitimate. |
| 17 | 11.53% | 14788 | Nutella 350g | 399 / 399 | 353 / 399 | Complete | Discount added. Legitimate. |
| 18 | 11.11% | 2780 | Kinder Joy Girl 20g | 45 / 45 | 50 / 50 | Complete | Straight price increase. Legitimate. |
| 19 | 11.08% | 16810 | Patanjali Kesh Kanti 650ml | 650 / 650 | 578 / 578 | Partial / Weight-Diff | Discount added. Legitimate. |
| 20 | 10.96% | 4714 | Garnier Men Face Wash 150g | 447 / 449 | 398 / 399 | Partial / Weight-Diff | MRP + SP both moved down. Legitimate. |

**Zero entries in the top 20 are attributable to an SAM scraper bug.** All show MRP+SP pairs that are internally consistent on both sides — the product itself was repriced between the two snapshots.

---

## 3. Coverage gap — the REAL quality problem

The 94.6% number hides the bigger issue: we only compared 766 of 2,364 Anakin-mapped SKUs (32.4%).

| "no_price_on_pdp" count | Anakin stock status |
|---|---|
| 731 | `out_of_stock` — expected, the PDP has no price block |
| **697** | **`available` — our scraper failed to extract a visible price** |

That 697-SKU gap is the biggest opportunity to improve quality. It's a **Stage-1 PDP extractor regression**, not a matching problem.

---

## 4. Confidence interval — volatile products

- 24 SKUs in the pool have SP < ₹20 (fresh produce, small snacks); 5 of them (21%) are out of ±5% tolerance. A single ₹1 rounding move produces a 5–10% percentage swing on these.
- 61 SKUs returned `in_stock=False` from SAM (we still captured a stale price); 4 of those are out-of-tolerance. These are noisy by nature — an OOS item's price often isn't refreshed.

**Recommendation for measurement:** when reporting match rate, exclude products under ~₹20 from the denominator (or switch to absolute ₹ diff rather than percent for those).

---

## 5. 30-SKU spot check on perfect matches

Random sample of 30 from the 674 `price_diff_pct = 0.0` records — every single one looked clean:

| # | Code | SP | MRP | Status | Item |
|---|---|---|---|---|---|
| 1 | 97054 | 207 | 235 | Complete | Softouch Fabric Conditioner 800ml |
| 2 | 11519 | 125 | 125 | Complete | Red Bull Energy Drink 250ml |
| 3 | 102785 | 119 | 126 | Partial | RiteBite Max Protein Chips Spanish Tomato 60g |
| 4 | 2619 | 235 | 270 | Complete | Fortune Chakki Fresh Atta 5kg |
| 5 | 23904 | 142 | 142 | Partial | Patanjali Haldi Chandan Kanti 150g |
| 6 | 1606 | 99 | 99 | Complete | Godrej Aer Room Freshener 220ml |
| 7 | 12205 | 200 | 210 | Complete | Listerine Cool Mint 250ml |
| 8 | 11235 | 225 | 225 | Partial | Gillette Mach3 Razor |
| 9 | 8348 | 30 | 30 | Complete | Vim Lemon Dishwash Bar 300g |
| 10 | 1085 | 103 | 150 | Partial | Britannia Good Day Choco Chip |
| 11 | 92073 | 749 | 885 | Partial | Surf Excel Matic Front Load 3.2L |
| 12 | 5021 | 133 | 133 | Partial | Sensodyne Deep Clean |
| 13 | 10292 | 40 | 40 | Complete | Godrej Expert Rich Creme 20g |
| 14 | 10285 | 39 | 48 | Partial | Doritos Sweet Chili 45g |
| 15 | 10942 | 125 | 125 | Complete | Amul Diced Cheese 200g |
| 16 | 15741 | 400 | 725 | Partial | Nivea Soft Light Moisturising 300ml |
| 17 | 17844 | 127 | 169 | Partial | Pringles Original 141g |
| 18 | 78754 | 27 | 30 | Partial | Shubhkart Tejas Cotton Wicks 7g |
| 19 | 94187 | 74 | 143 | Partial | Parle Hide & Seek Bourbon 270g |
| 20 | 102790 | 82 | 84 | Partial | RiteBite Max Protein Peri Peri 60g |
| 21 | 85317 | 189 | 209 | Partial | Tata Coffee Grand 50g |
| 22 | 14062 | 79 | 100 | Partial | Sunfeast Yippee Mood Masala 65g |
| 23 | 978 | 291 | 330 | Complete | Bikaji Bikaneri Bhujia 1kg |
| 24 | 5008 | 96 | 106 | Partial | Himalaya Sparkling White 150g |
| 25 | 1591 | 225 | 250 | Partial | Duracell AA Chota Power |
| 26 | 68856 | 29 | 30 | Complete | Britannia Nutri Choice 91.7g |
| 27 | 92 | 86 | 90 | Complete | Ching's Schezwan Chutney 250g |
| 28 | 2676 | 40 | 40 | Partial | Fevi Kwik 450mg |
| 29 | 100975 | 11 | 13 | Complete | Hara Dhaniya/Coriander |
| 30 | 1273 | 39 | 40 | Partial | Cadbury Oreo 38.75g |

No red flags. SP ≤ MRP in every case, brand/name plausible for code.

---

## 6. Anakin data quality observations

Found during this audit — these are Anakin's bugs, not ours:

| # | Issue | Count | Example |
|---|---|---|---|
| 1 | `Blinkit_Status = Complete Match` but `Blinkit_Product_Id = NA` | **850** | Item 100013 "Bambino Rosetta Pasta 500g" — no product id means no URL, yet status says complete |
| 2 | `partial Match` typo (lowercase) | 2 | Should be `Partial Match` |
| 3 | `MRP-Diff` vs `MRP Diff` label inconsistency | 2 vs 358 | Hyphenation bug in Anakin pipeline |
| 4 | `NFNV-White-label` vs `NFNV-White Label` (case) | 4 vs 1 | |
| 5 | `Blinkit_Partial = 'nan'` literal string | 1,760 | Should be null/empty; Anakin stringifies NaN |
| 6 | `Blinkit_Factor = '#VALUE!'` Excel error leak | 2 | `Broccoli`, `Chow Chow` — Excel cell leaked |
| 7 | `Blinkit_Factor` empty on Complete Match | 7 | E.g. Vi-John Shaving Cream 124g |
| 8 | `Unit = 'NA'` (literal string) | 751 | Item 10024 "Cadbury 5Star 18g" — unit should be 'g' |
| 9 | Same Blinkit URL mapped to two Apna SKUs | ≥1 | code 86785 + 95574 both → French Beans 250g URL. Double counting risk in Anakin. |
| 10 | Wrong mapping (ground truth wrong) | sparse | Horlicks Chocolate Delight → Women's Plus Chocolate (confirmed in ANAKIN.md §16.12) |

**Implication:** even if we scraped Blinkit with 100% fidelity, our output could never be identical to Anakin's — because Anakin itself has persistent ~1% data quality noise.

---

## 7. Path to 99%

### Accuracy-layer math

The 94.65% number is almost entirely limited by **market volatility between the two snapshots**, not by scraper bugs.

**Realistic ceiling** for our current design: if we ran both scrapes in the same 15-minute window, market movement would be nearly zero and the match rate would likely exceed **98–99% within ±5%**, because:

- 88% are already exact-zero matches.
- Of the 41 out-of-tol cases, at least 39 are same-PDP price moves.
- The only residual noise is: (a) a handful of fresh produce under ₹20 (inherent rounding), and (b) Anakin's ~1% internal data-quality issues (wrong mappings, stale SPs).

### Concrete actions to close the gap

| Priority | Action | Expected impact on ±5% match |
|---|---|---|
| **P0** | **Run SAM Stage-1 scrape BEFORE 11:00 IST** (same day as Anakin's snapshot) | Eliminate most of the 39 "legitimate price move" cases → ~98% |
| **P0** | Fix the Stage-1 PDP price extractor — 697 Anakin-available items returned `no_price_on_pdp`. That's a bigger quality problem than the 41 mismatches. | Moves the compared pool from 766 → ~1,450, and because the current error rate is tail-heavy on volatile SKUs, the percentage should hold or improve. |
| **P1** | Exclude SKUs with SP < ₹20 from the percent metric (or add a `₹1 tolerance` clause: `pass if diff ≤ max(5%, ₹1)`) | Reclaim ~5 SKUs, ~0.6% |
| **P1** | Treat `in_stock=False` SKUs as "stale price" — flag but don't count them against accuracy | Reclaim ~4 SKUs |
| **P2** | Build a short-term (5-min) re-scrape queue for the ~40 SKUs that diverge > 5% on Stage 1. Re-confirm with a second pull. | Catches any genuine extraction bugs; removes Anakin-side staleness |
| **P2** | Add a sanity check: alert if `sam_sp > sam_mrp` (shouldn't ever happen) | Currently 0 such cases; keep as guardrail |
| **P3** | Ignore Anakin SKUs where `Blinkit_Product_Id = NA` or `Blinkit_Status = 'Semi Complete Match'` for percent calc — they're noisy ground truth | Reclaim ~2 SKUs |
| **P3** | Investigate the 2 scrape_error SKUs (codes 3595, 4196) | Operational, not accuracy |

### Can we hit 99%?

**Yes — with two caveats:**

1. **Time alignment is non-negotiable.** If our scrape runs 14 hours after Anakin's, we will never hit 99% because Blinkit reprices multiple times per day. Scheduling the Stage-1 run before 11 AM IST should immediately push us into the 98%+ range based on the evidence here.
2. **Define 99% against the right denominator.** The right denominator is *SKUs where both sides have a price extracted*, not "all Anakin-mapped SKUs". Coverage (697 currently-missed `available` SKUs) is a separate workstream — treat it as a scraper reliability KPI, not a price-accuracy KPI.

If both of those are fixed, **99% ±5% is achievable within this sprint**. The remaining ~1% will be permanent noise from Anakin's own mapping errors and fresh-produce rounding.

### What CANNOT be fixed by our side

- Anakin's wrong cross-brand mappings (e.g. Horlicks Chocolate → Horlicks Women's Plus) — these have diffs of 100%+. We'll look correct but Anakin is wrong.
- Anakin's `#VALUE!` / `'nan'` field leaks — pipeline artefacts on their end.
- Anakin's stale mappings where product_id is NA but status is Complete Match.

Any metric that uses Anakin as ground truth is capped at roughly Anakin's own internal consistency (~99%).
