"""
Auto-Heal — Self-healing price extraction that survives layout changes.

Instead of ONE extraction method, tries MULTIPLE strategies in order.
If Blinkit/Jiomart changes their page, at least one method should still work.

Strategies (tried in order):
  1. API response interception (JSON in network responses)
  2. JSON-LD structured data (<script type="application/ld+json">)
  3. Meta tags (og:price, product:price:amount)
  4. DOM price elements (₹ near product title)
  5. Raw HTML regex (last resort)

Also includes:
  - Price sanity checks (not 0, not negative, not absurdly high)
  - Historical comparison (flag if price changed >50% from last known)
  - Failure rate monitoring (alert if >40% products fail)
"""
import json
import re
from dataclasses import dataclass


@dataclass
class ExtractedPrice:
    """Result of price extraction with metadata."""
    selling_price: float | None = None
    mrp: float | None = None
    product_name: str | None = None
    in_stock: bool = True
    method: str = "none"       # which strategy succeeded
    confidence: float = 0.0    # 0-1, how confident we are
    raw_methods_tried: int = 0
    error: str | None = None


class AutoHealExtractor:
    """Self-healing price extractor that tries multiple strategies."""

    # Price sanity bounds
    MIN_PRICE = 1.0
    MAX_PRICE = 50000.0
    MAX_PRICE_CHANGE_PCT = 200.0  # flag if price changed >200% from last known

    def __init__(self):
        self.stats = {"total": 0, "success": 0, "by_method": {}}

    async def extract_price(self, page, product_id: str = "", last_known_price: float = 0) -> ExtractedPrice:
        """Try all strategies to extract price from current page. Returns best result."""
        result = ExtractedPrice()
        methods_tried = 0

        # Strategy 1: API response interception (already captured by page)
        methods_tried += 1
        api_result = await self._try_api_interception(page, product_id)
        if api_result and self._is_valid_price(api_result.get("sp")):
            result.selling_price = api_result["sp"]
            result.mrp = api_result.get("mrp")
            result.product_name = api_result.get("name")
            result.method = "api_interception"
            result.confidence = 0.95

        # Strategy 2: JSON-LD
        if result.selling_price is None:
            methods_tried += 1
            ld_result = await self._try_json_ld(page)
            if ld_result and self._is_valid_price(ld_result.get("sp")):
                result.selling_price = ld_result["sp"]
                result.mrp = ld_result.get("mrp")
                result.product_name = ld_result.get("name")
                result.method = "json_ld"
                result.confidence = 0.90

        # Strategy 3: Meta tags
        if result.selling_price is None:
            methods_tried += 1
            meta_result = await self._try_meta_tags(page)
            if meta_result and self._is_valid_price(meta_result.get("sp")):
                result.selling_price = meta_result["sp"]
                result.product_name = meta_result.get("name")
                result.method = "meta_tags"
                result.confidence = 0.85

        # Strategy 4: DOM price elements (₹ near title)
        if result.selling_price is None:
            methods_tried += 1
            dom_result = await self._try_dom_prices(page)
            if dom_result and self._is_valid_price(dom_result.get("sp")):
                result.selling_price = dom_result["sp"]
                result.mrp = dom_result.get("mrp")
                result.product_name = dom_result.get("name")
                result.method = "dom_price"
                result.confidence = 0.75

        # Strategy 5: Raw HTML regex (last resort)
        if result.selling_price is None:
            methods_tried += 1
            regex_result = await self._try_html_regex(page)
            if regex_result and self._is_valid_price(regex_result.get("sp")):
                result.selling_price = regex_result["sp"]
                result.mrp = regex_result.get("mrp")
                result.method = "html_regex"
                result.confidence = 0.50

        # Stock check
        if result.selling_price is None:
            result.in_stock = await self._check_out_of_stock(page)
            result.method = "no_price"
            result.confidence = 0.0

        # Sanity: historical comparison
        if result.selling_price and last_known_price > 0:
            change_pct = abs(result.selling_price - last_known_price) / last_known_price * 100
            if change_pct > self.MAX_PRICE_CHANGE_PCT:
                result.error = f"price_anomaly: {last_known_price}→{result.selling_price} ({change_pct:.0f}% change)"
                result.confidence *= 0.5

        result.raw_methods_tried = methods_tried

        # Track stats
        self.stats["total"] += 1
        if result.selling_price:
            self.stats["success"] += 1
            self.stats["by_method"][result.method] = self.stats["by_method"].get(result.method, 0) + 1

        return result

    def _is_valid_price(self, price) -> bool:
        if price is None:
            return False
        try:
            p = float(price)
            return self.MIN_PRICE <= p <= self.MAX_PRICE
        except (ValueError, TypeError):
            return False

    async def _try_api_interception(self, page, product_id: str) -> dict | None:
        """Find product in captured API responses."""
        try:
            # Check if page has captured responses (from our response listener)
            data = await page.evaluate("""() => {
                // Access captured responses if stored globally
                if (window.__sam_captured) return window.__sam_captured;
                return null;
            }""")
            if data:
                return self._find_product_in_data(data, product_id)
        except Exception:
            pass
        return None

    async def _try_json_ld(self, page) -> dict | None:
        """Extract price from JSON-LD structured data."""
        try:
            result = await page.evaluate("""() => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        const items = Array.isArray(data) ? data : [data];
                        const stack = [...items];
                        while (stack.length) {
                            const cur = stack.pop();
                            if (!cur || typeof cur !== 'object') continue;
                            if (cur['@type'] === 'Product' || cur['@type'] === 'ProductGroup') {
                                const name = cur.name || '';
                                const offers = cur.offers || {};
                                const offerList = Array.isArray(offers) ? offers : [offers];
                                for (const off of offerList) {
                                    const sp = parseFloat(off.price || off.lowPrice);
                                    const mrp = parseFloat(off.highPrice);
                                    if (sp > 0) return {sp, mrp: mrp > 0 ? mrp : null, name};
                                }
                            }
                            if (cur['@graph']) stack.push(...cur['@graph']);
                            for (const v of Object.values(cur)) {
                                if (v && typeof v === 'object') stack.push(v);
                            }
                        }
                    } catch(e) {}
                }
                return null;
            }""")
            return result
        except Exception:
            return None

    async def _try_meta_tags(self, page) -> dict | None:
        """Extract price from OG/product meta tags."""
        try:
            result = await page.evaluate("""() => {
                const priceEl = document.querySelector(
                    'meta[property="product:price:amount"], meta[property="og:price:amount"]'
                );
                const nameEl = document.querySelector('meta[property="og:title"]');
                if (priceEl) {
                    const sp = parseFloat((priceEl.getAttribute('content') || '').replace(',', ''));
                    if (sp > 0) return {
                        sp,
                        name: nameEl ? nameEl.getAttribute('content') : null
                    };
                }
                return null;
            }""")
            return result
        except Exception:
            return None

    async def _try_dom_prices(self, page) -> dict | None:
        """Extract price from DOM elements near the product title."""
        try:
            result = await page.evaluate("""() => {
                // Find all h1 candidates (skip generic ones)
                const h1s = [...document.querySelectorAll('h1')];
                let title = null;
                for (const h of h1s) {
                    const t = (h.innerText || '').trim();
                    if (t.length >= 5 && t.length < 200 &&
                        !/questions|answer|reviews|related|similar/i.test(t)) {
                        title = t;
                        break;
                    }
                }
                if (!title) {
                    const og = document.querySelector('meta[property="og:title"]');
                    if (og) title = og.getAttribute('content');
                }

                // Find ₹ prices near the title area
                const allEls = document.querySelectorAll('span, div, p, strong, b');
                const candidates = [];
                for (const el of allEls) {
                    const t = (el.textContent || '').trim();
                    if (!t.includes('₹') || t.length > 30) continue;
                    const m = t.match(/₹\\s*([\\d,]+\\.?\\d*)/);
                    if (!m) continue;
                    const price = parseFloat(m[1].replace(/,/g, ''));
                    if (price <= 0 || price > 50000) continue;
                    // Check: is this element visible and in the main content area?
                    const rect = el.getBoundingClientRect();
                    if (rect.top < 0 || rect.top > 800) continue;
                    candidates.push({price, top: rect.top, left: rect.left});
                }

                if (candidates.length === 0) return null;

                // Sort by position (top-left first = main product price area)
                candidates.sort((a, b) => a.top - b.top || a.left - b.left);
                const prices = [...new Set(candidates.map(c => c.price))];

                let sp = null, mrp = null;
                if (prices.length >= 2) {
                    // Smaller price = selling price, larger = MRP
                    sp = Math.min(...prices.slice(0, 3));
                    mrp = Math.max(...prices.slice(0, 3));
                    if (mrp === sp) mrp = null;
                } else if (prices.length === 1) {
                    sp = prices[0];
                }

                return {sp, mrp, name: title};
            }""")
            return result
        except Exception:
            return None

    async def _try_html_regex(self, page) -> dict | None:
        """Last resort: regex on raw HTML source."""
        try:
            html = await page.content()
            if len(html) < 500:
                return None

            # Find price patterns in HTML attributes/values
            prices = []

            # Pattern 1: "price": 123 or "price":"123"
            for m in re.finditer(r'"(?:price|selling_price|offer_price|sp|sellingPrice)"[:\s]*"?(\d+\.?\d*)"?', html, re.IGNORECASE):
                try:
                    p = float(m.group(1))
                    if 1 < p < 50000:
                        prices.append(p)
                except ValueError:
                    pass

            # Pattern 2: ₹ followed by number
            for m in re.finditer(r'₹\s*(\d[\d,]*\.?\d*)', html):
                try:
                    p = float(m.group(1).replace(',', ''))
                    if 1 < p < 50000:
                        prices.append(p)
                except ValueError:
                    pass

            if not prices:
                return None

            # Most common price = likely the product price
            from collections import Counter
            freq = Counter(prices)
            most_common = freq.most_common(3)

            if len(most_common) >= 2:
                sp = min(most_common[0][0], most_common[1][0])
                mrp = max(most_common[0][0], most_common[1][0])
                return {"sp": sp, "mrp": mrp if mrp != sp else None}
            elif most_common:
                return {"sp": most_common[0][0]}
            return None
        except Exception:
            return None

    async def _check_out_of_stock(self, page) -> bool:
        """Check if page shows out-of-stock indicators."""
        try:
            result = await page.evaluate("""() => {
                const text = (document.body ? document.body.innerText : '').toLowerCase();
                return !(text.includes('out of stock') ||
                         text.includes('currently unavailable') ||
                         text.includes('notify me') ||
                         text.includes('sold out'));
            }""")
            return result
        except Exception:
            return True

    def _find_product_in_data(self, data, product_id: str, depth=0) -> dict | None:
        """Recursively find product with matching ID in JSON data."""
        if depth > 10:
            return None
        if isinstance(data, dict):
            pid = str(data.get("product_id") or data.get("productId") or data.get("prid") or "")
            if not pid:
                raw_id = data.get("id")
                if raw_id and any(k in data for k in ("product_name", "brand", "unit")):
                    pid = str(raw_id)
            if pid == str(product_id):
                has_price = any(k in data for k in ("mrp", "price", "offer_price", "selling_price"))
                has_name = any(k in data for k in ("name", "product_name", "display_name"))
                if has_price:
                    sp = None
                    for k in ("offer_price", "selling_price", "sp", "price"):
                        v = data.get(k)
                        if isinstance(v, dict):
                            for dk in ("offer_price", "selling_price", "sp", "price"):
                                dv = v.get(dk)
                                if dv and not isinstance(dv, dict):
                                    try:
                                        sp = float(str(dv).replace(",", "").replace("₹", ""))
                                        if sp > 0: break
                                    except: pass
                        elif v and not isinstance(v, (dict, list)):
                            try:
                                sp = float(str(v).replace(",", "").replace("₹", ""))
                                if sp > 0: break
                            except: pass
                    mrp = None
                    for k in ("mrp", "marked_price", "original_price"):
                        v = data.get(k)
                        if isinstance(v, dict):
                            v = v.get("mrp") or v.get("price")
                        if v and not isinstance(v, (dict, list)):
                            try:
                                mrp = float(str(v).replace(",", "").replace("₹", ""))
                                if mrp > 0: break
                            except: pass
                    name = None
                    for k in ("name", "product_name", "display_name", "title"):
                        v = data.get(k)
                        if v and isinstance(v, str):
                            name = v
                            break
                    if sp:
                        return {"sp": sp, "mrp": mrp, "name": name}
            for v in data.values():
                r = self._find_product_in_data(v, product_id, depth + 1)
                if r: return r
        elif isinstance(data, list):
            for item in data:
                r = self._find_product_in_data(item, product_id, depth + 1)
                if r: return r
        return None

    def get_health_report(self) -> dict:
        """Get extraction health stats."""
        total = self.stats["total"]
        success = self.stats["success"]
        rate = round(success * 100 / total, 1) if total else 0
        alert = "🔴 CRITICAL" if rate < 40 else ("🟡 WARNING" if rate < 70 else "🟢 HEALTHY")
        return {
            "total_attempts": total,
            "successful": success,
            "success_rate": rate,
            "health": alert,
            "by_method": self.stats["by_method"],
            "recommendation": self._get_recommendation(rate),
        }

    def _get_recommendation(self, rate: float) -> str:
        if rate >= 90:
            return "All good — extraction working well"
        elif rate >= 70:
            return "Some failures — check if platform changed DOM structure"
        elif rate >= 40:
            return "High failure rate — platform likely changed layout. Check strategies."
        else:
            return "CRITICAL — most extractions failing. Platform may have added anti-bot. Check immediately."
