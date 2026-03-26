import asyncio
import json
import re

from app.models.product import Product
from app.scrapers.base_scraper import BaseScraper


class ZeptoScraper(BaseScraper):
    platform_name = "zepto"
    base_url = "https://www.zepto.com"

    CATEGORY_MAP = {
        "Fruits & Vegetables": ["/cn/fruits-vegetables"],
        "Dairy, Bread & Eggs": ["/cn/dairy-bread-eggs"],
        "Atta, Rice, Oil & Dal": ["/cn/atta-rice-oil-dal"],
        "Masala & Dry Fruits": ["/cn/masala-dry-fruits"],
        "Sweet Cravings": ["/cn/sweet-cravings"],
        "Frozen Food": ["/cn/frozen-food"],
        "Packaged Food": ["/cn/packaged-food"],
        "Drinks & Juices": ["/cn/drinks-juices"],
        "Tea & Coffee": ["/cn/tea-coffee"],
        "Biscuits & Snacks": ["/cn/biscuits-snacks"],
        "Personal Care": ["/cn/personal-care"],
        "Home & Cleaning": ["/cn/home-cleaning"],
        "Baby Care": ["/cn/baby-care"],
        "Pharma": ["/cn/pharma"],
        "Pet Care": ["/cn/pet-care"],
        "Household": ["/cn/household"],
    }

    CATEGORY_SEARCH_MAP = {
        "Fruits & Vegetables": ["fruits", "vegetables"],
        "Dairy, Bread & Eggs": ["dairy", "breakfast"],
        "Atta, Rice, Oil & Dal": ["staples"],
        "Masala & Dry Fruits": ["masala", "dry_fruits"],
        "Sweet Cravings": ["sweet", "snacks"],
        "Frozen Food": ["frozen"],
        "Packaged Food": ["breakfast", "snacks"],
        "Drinks & Juices": ["beverages"],
        "Tea & Coffee": ["tea_coffee"],
        "Biscuits & Snacks": ["snacks"],
        "Personal Care": ["personal_care"],
        "Home & Cleaning": ["cleaning"],
        "Baby Care": ["baby_health"],
        "Pharma": ["baby_health"],
        "Pet Care": ["pet_care"],
        "Household": ["kitchen_home", "cleaning"],
    }

    FALLBACK_CATEGORY_SLUGS = [path for paths in CATEGORY_MAP.values() for path in paths]

    async def _on_response(self, response):
        """Capture JSON responses from both main domain and BFF gateway."""
        try:
            url = response.url
            ct = response.headers.get("content-type", "")
            is_json = "json" in ct
            is_bff = "bff-gateway.zepto.com" in url
            # BFF responses may use octet-stream or RSC format
            if (is_json or is_bff) and response.status == 200:
                body = await response.text()
                if len(body) > 100 and any(kw in body.lower() for kw in ["product", "price", "mrp", "name", "selling", "inventory"]):
                    try:
                        data = json.loads(body)
                        self._captured_responses.append({"url": url, "data": data})
                    except json.JSONDecodeError:
                        # Try line-delimited JSON (RSC streaming)
                        for line in body.split("\n"):
                            line = line.strip()
                            if not line or len(line) < 50:
                                continue
                            try:
                                data = json.loads(line)
                                self._captured_responses.append({"url": url, "data": data})
                            except json.JSONDecodeError:
                                continue
        except Exception:
            pass

    async def _extract_products_from_dom(self) -> int:
        """Extract products from Zepto's server-rendered DOM.

        Zepto product cards contain:
        ADD | ₹price | ₹mrp | ₹discount | OFF | Product Name | Unit | [tags] | [rating]
        Images from cdn.zeptonow.com
        """
        try:
            products = await self.page.evaluate(r"""() => {
                const results = [];
                const seen = new Set();
                const allEls = document.querySelectorAll('div, a');
                for (const el of allEls) {
                    const text = el.innerText?.trim() || '';
                    if (!text.includes('\u20B9') || text.length < 20 || text.length > 600) continue;
                    const img = el.querySelector('img[src*="cdn.zeptonow.com"]');
                    if (!img) continue;
                    const cc = el.children.length;
                    if (cc < 2 || cc > 25) continue;
                    // Check this is a leaf-level card
                    let isLeaf = true;
                    for (const child of el.children) {
                        const ct = child.innerText?.trim() || '';
                        if (ct.includes('\u20B9') && child.querySelector('img[src*="cdn.zeptonow.com"]') && ct.length > 20) {
                            isLeaf = false;
                            break;
                        }
                    }
                    if (!isLeaf) continue;

                    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                    let name = '', unit = null;
                    const prices = [];
                    const skipWords = ['ADD', 'OFF', 'Bestseller', 'New', 'Sold Out', 'Out of Stock',
                                       'Added', 'Fresh', 'Super Saver'];

                    for (const line of lines) {
                        const priceMatch = line.match(/^\u20B9([\d,]+)/);
                        if (priceMatch) {
                            prices.push(parseFloat(priceMatch[1].replace(/,/g, '')));
                        } else if (!skipWords.some(w => line === w)
                                   && !line.match(/^\d+\.\d+$/)
                                   && !line.match(/^\([\d.]+[km]?\)$/i)
                                   && !line.match(/^\d+% off$/i)
                                   && !line.match(/^\u20B9\d/)
                                   && line.length > 2) {
                            if (!name) {
                                name = line;
                            } else if (!unit && line.length < 50 &&
                                       (line.match(/\d/) || line.includes('pack') || line.includes('pc') ||
                                        line.includes('kg') || line.includes('gm') || line.includes('ml') ||
                                        line.includes('ltr') || line.includes('L)'))) {
                                unit = line;
                            }
                        }
                    }

                    if (prices.length >= 1 && name && name.length > 3 && !seen.has(name)) {
                        seen.add(name);
                        const price = prices[0];
                        const mrp = prices.length >= 2 ? prices[1] : null;
                        results.push({
                            name, price,
                            mrp: mrp && mrp !== price ? mrp : null,
                            unit,
                            img: img.src || null,
                        });
                    }
                }
                return results;
            }""")

            count = 0
            for p in (products or []):
                pid = p['name']
                if pid in self._seen_ids:
                    continue
                self._seen_ids.add(pid)

                self.products.append(Product(
                    product_name=p['name'],
                    brand=p['name'].split()[0],
                    price=p['price'],
                    mrp=p['mrp'],
                    unit=p.get('unit'),
                    category=None,
                    sub_category=None,
                    platform=self.platform_name,
                    pincode=self.pincode,
                    in_stock=True,
                    scraped_at=self.now_iso(),
                    image_url=p.get('img'),
                ))
                count += 1
            return count
        except Exception:
            return 0

    async def _visit_and_collect(self, url, scroll_times=5):
        """Override to add DOM extraction for Zepto."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._wait_for_network_settle(0.5, 3.0)
            await self._scroll_page(times=scroll_times, delay=0.8)

            # Try API response parsing first
            count = self._process_responses()

            # Also extract from DOM (Zepto uses RSC, products are server-rendered)
            dom_count = await self._extract_products_from_dom()
            count += dom_count

            await self._report_progress()
            return count
        except Exception as e:
            print(f"[{self.platform_name}] Visit {url} error: {e}")
            return 0

    async def _search_and_capture(self, search_url_fn):
        """Override to use custom _visit_and_collect with DOM extraction."""
        consecutive_empty = 0
        max_consecutive_empty = 10
        for term in self._get_filtered_search_terms():
            if len(self.products) >= self.max_products:
                break
            if consecutive_empty >= max_consecutive_empty:
                print(f"[{self.platform_name}] Early exit: {max_consecutive_empty} consecutive empty searches. "
                      f"Total: {len(self.products)}.")
                break
            try:
                before = len(self.products)
                url = search_url_fn(term)
                await self._visit_and_collect(url, scroll_times=5)

                after = len(self.products)
                if after > before:
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
            except Exception as e:
                print(f"[{self.platform_name}] Search '{term}' error: {e}")
                consecutive_empty += 1
                continue

    async def _set_location(self):
        """Set Zepto location via cookies and localStorage."""
        await self.context.add_cookies([
            {"name": "pincode", "value": self.pincode, "domain": ".zepto.com", "path": "/"},
            {"name": "user_pincode", "value": self.pincode, "domain": ".zepto.com", "path": "/"},
            {"name": "latitude", "value": str(self.lat), "domain": ".zepto.com", "path": "/"},
            {"name": "longitude", "value": str(self.lng), "domain": ".zepto.com", "path": "/"},
            {"name": "lat", "value": str(self.lat), "domain": ".zepto.com", "path": "/"},
            {"name": "lng", "value": str(self.lng), "domain": ".zepto.com", "path": "/"},
        ])

    async def _set_local_storage(self):
        """Set localStorage keys that Zepto's app reads for location."""
        await self.page.evaluate(f"""() => {{
            localStorage.setItem('latitude', '{self.lat}');
            localStorage.setItem('longitude', '{self.lng}');
            localStorage.setItem('store_id', '');
            localStorage.setItem('user_position', JSON.stringify({{
                latitude: {self.lat},
                longitude: {self.lng}
            }}));
            localStorage.setItem('serviceability', JSON.stringify({{
                serviceable: true,
                pincode: '{self.pincode}',
                latitude: {self.lat},
                longitude: {self.lng}
            }}));
            localStorage.setItem('marketplace', JSON.stringify({{
                latitude: {self.lat},
                longitude: {self.lng}
            }}));
        }}""")

    async def _try_ui_location(self):
        """Try to set location via UI if a location prompt is visible."""
        try:
            body_text = await self.page.evaluate("() => document.body.innerText.substring(0, 2000)")
            location_keywords = ["deliver", "location", "enter your", "pincode", "address", "where do you",
                                 "select location"]
            if not any(kw in body_text.lower() for kw in location_keywords):
                return False

            loc_selectors = [
                'button:has-text("Enter")',
                'button:has-text("Location")',
                'button:has-text("Deliver")',
                'button:has-text("Change")',
                'text="Select Location"',
                '[data-testid="location"]',
            ]
            for sel in loc_selectors:
                try:
                    el = self.page.locator(sel).first
                    if await el.is_visible(timeout=1500):
                        await el.click()
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            input_selectors = [
                'input[placeholder*="pincode"]',
                'input[placeholder*="area"]',
                'input[placeholder*="location"]',
                'input[placeholder*="search"]',
                'input[placeholder*="address"]',
                'input[type="text"]',
            ]
            for sel in input_selectors:
                try:
                    inp = self.page.locator(sel).first
                    if await inp.is_visible(timeout=1500):
                        await inp.fill(self.pincode)
                        await asyncio.sleep(2)
                        for sug_sel in ['li:first-child', 'div[role="option"]:first-child', '[class*="suggestion"]:first-child']:
                            try:
                                sug = self.page.locator(sug_sel).first
                                if await sug.is_visible(timeout=2000):
                                    await sug.click()
                                    await asyncio.sleep(2)
                                    return True
                            except Exception:
                                continue
                        await inp.press("Enter")
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    async def _discover_categories(self):
        """Dynamic 3-tier category discovery: DOM links -> API responses -> fallback slugs."""
        filtered_paths = set(self._get_filtered_category_paths())
        categories = []

        # Tier 1: DOM links
        try:
            page_cats = await self.page.evaluate("""
                () => [...document.querySelectorAll('a[href*="/cn/"]')]
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && h.startsWith('/cn/'))
            """)
            discovered = list(set(page_cats or []))
            if self.selected_categories and "all" not in self.selected_categories:
                categories = [c for c in discovered if c in filtered_paths]
            else:
                categories = discovered
        except Exception:
            pass

        if len(categories) >= 3:
            return categories[:30]

        # Tier 2: Parse API responses for category data
        try:
            for resp in self._captured_responses:
                data = resp.get("data", {})
                self._extract_category_urls(data, categories)
                if len(categories) >= 3:
                    found = list(set(categories))
                    if self.selected_categories and "all" not in self.selected_categories:
                        found = [c for c in found if c in filtered_paths]
                    return found[:30]
        except Exception:
            pass

        # Tier 3: Fallback slugs
        if len(categories) < 3:
            categories = list(filtered_paths) if filtered_paths else self.FALLBACK_CATEGORY_SLUGS
        return categories[:30]

    def _extract_category_urls(self, data, categories, depth=0):
        """Recursively extract category URLs from API response data."""
        if depth > 5:
            return
        if isinstance(data, dict):
            for key in ["slug", "url", "href", "path", "link"]:
                val = data.get(key)
                if val and isinstance(val, str) and "/cn/" in val:
                    categories.append(val if val.startswith("/") else f"/{val}")
            for val in data.values():
                self._extract_category_urls(val, categories, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self._extract_category_urls(item, categories, depth + 1)

    async def scrape_all(self) -> list[Product]:
        try:
            await self.init_browser()
            print(f"[zepto] Starting scrape for pincode {self.pincode}")

            # Navigate to homepage and set location
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)

            await self._set_location()
            await self._set_local_storage()

            # Reload with location set
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Try UI-based location setting
            await self._try_ui_location()

            # Extract products from homepage DOM
            homepage_count = await self._extract_products_from_dom()
            # Also process any API responses
            api_count = self._process_responses()
            print(f"[zepto] Homepage: {homepage_count} DOM + {api_count} API products")

            # Phase 1: Search (most reliable for Zepto — server-rendered products)
            await self._search_and_capture(
                lambda term: f"{self.base_url}/search?query={term}"
            )
            print(f"[zepto] After search: {len(self.products)} products")

            # Phase 2: Deep crawl categories (if we need more)
            if len(self.products) < self.max_products:
                seed_categories = await self._discover_categories()
                print(f"[zepto] Discovered {len(seed_categories)} categories, crawling...")

                visited = set()
                queue = list(seed_categories)
                consecutive_empty = 0

                while queue and len(self.products) < self.max_products and len(visited) < 200:
                    cat = queue.pop(0)
                    if cat in visited:
                        continue
                    visited.add(cat)

                    url = cat if cat.startswith('http') else f"{self.base_url}{cat}"
                    new = await self._visit_and_collect(url, scroll_times=6)

                    if new > 0:
                        consecutive_empty = 0
                        print(f"[zepto] [{len(visited)}] +{new} (total: {len(self.products)})")
                    else:
                        consecutive_empty += 1

                    # Discover new subcategory links
                    try:
                        page_links = await self.page.evaluate("""
                            () => [...document.querySelectorAll('a[href*="/cn/"]')]
                                .map(a => a.getAttribute('href'))
                                .filter(h => h && h.startsWith('/cn/'))
                        """)
                        for link in (page_links or []):
                            if link not in visited and link not in set(queue):
                                queue.append(link)
                    except Exception:
                        pass

                    if consecutive_empty >= 15 and len(visited) >= 10:
                        print(f"[zepto] Early exit: {consecutive_empty} consecutive empty. {len(self.products)} products.")
                        break

            # Fallback: __NEXT_DATA__ extraction
            if len(self.products) < 5:
                html_products = await self._extract_from_page_html()
                for rp in html_products:
                    pid = str(rp.get("id") or rp.get("name", ""))
                    if pid in self._seen_ids:
                        continue
                    self._seen_ids.add(pid)
                    product = self._parse_generic_product(rp)
                    if product:
                        self.products.append(product)

            print(f"[zepto] Final: {len(self.products)} products for {self.pincode}")
            return self.products[:self.max_products]
        finally:
            await self.close()
