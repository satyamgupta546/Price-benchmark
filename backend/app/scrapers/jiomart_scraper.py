import asyncio
import json
import random
import re

from playwright.async_api import async_playwright

from app.config import settings
from app.models.product import Product
from app.scrapers.base_scraper import BaseScraper

FIREFOX_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


class JioMartScraper(BaseScraper):
    platform_name = "jiomart"
    base_url = "https://www.jiomart.com"

    # Hardcoded fallback — URLs may go stale; _discover_categories() refreshes them.
    CATEGORY_MAP = {
        "Fruits & Vegetables": ["/c/groceries/fruits-vegetables/219"],
        "Dairy & Bakery": ["/c/groceries/dairy-bakery/61"],
        "Cooking Essentials": ["/c/groceries/cooking-essentials/28984"],
        "Biscuits, Drinks & Packaged Foods": ["/c/groceries/biscuits-drinks-packaged-foods/28997"],
        "Personal Care": ["/c/groceries/personal-care/91"],
        "Beauty": ["/c/groceries/beauty/6607"],
        "Home": ["/c/groceries/home/36"],
        "Mom & Baby Care": ["/c/groceries/mom-baby-care/2551"],
    }

    # Keywords used to fuzzy-match discovered URLs back to CATEGORY_MAP display names.
    # Each entry: display_name -> list of substrings to look for in the URL slug.
    _CATEGORY_KEYWORDS = {
        "Fruits & Vegetables": ["fruit", "vegetable"],
        "Dairy & Bakery": ["dairy", "bakery"],
        "Cooking Essentials": ["cooking", "essentials", "staple", "masala", "spice", "oil", "rice", "atta", "dal"],
        "Biscuits, Drinks & Packaged Foods": ["biscuit", "drink", "packaged", "snack", "beverage"],
        "Personal Care": ["personal-care", "personal_care"],
        "Beauty": ["beauty", "cosmetic"],
        "Home": ["/home/", "cleaning", "household"],
        "Mom & Baby Care": ["mom", "baby", "infant"],
    }

    CATEGORY_SEARCH_MAP = {
        "Fruits & Vegetables": ["fruits", "vegetables"],
        "Dairy & Bakery": ["dairy", "breakfast"],
        "Cooking Essentials": ["staples", "masala"],
        "Biscuits, Drinks & Packaged Foods": ["snacks", "beverages", "tea_coffee", "breakfast"],
        "Personal Care": ["personal_care"],
        "Beauty": ["personal_care"],
        "Home": ["cleaning", "kitchen_home"],
        "Mom & Baby Care": ["baby_health"],
    }

    async def _discover_categories(self, page) -> dict[str, list[str]]:
        """Visit /c/groceries/2 and map discovered links back to CATEGORY_MAP names.

        Returns a dict with the same keys as CATEGORY_MAP but with live URLs.
        Falls back to the hardcoded CATEGORY_MAP on any failure.
        """
        try:
            await page.goto(f"{self.base_url}/c/groceries/2",
                            wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            raw_links = await page.evaluate("""() => {
                const anchors = document.querySelectorAll('a[href*="/c/groceries"]');
                const seen = new Set();
                const results = [];
                for (const a of anchors) {
                    const href = a.getAttribute('href');
                    if (!href || href === '/c/groceries/2') continue;
                    // Normalise: drop query string and trailing slash
                    const clean = href.split('?')[0].replace(/\\/$/, '');
                    if (seen.has(clean)) continue;
                    seen.add(clean);
                    // Grab the visible text for extra matching signal
                    const text = (a.innerText || a.textContent || '').trim();
                    results.push({href: clean, text: text});
                }
                return results;
            }""")

            if not raw_links or len(raw_links) < 3:
                print("[jiomart] Category discovery: too few links found, using hardcoded fallback")
                return dict(self.CATEGORY_MAP)

            # Build the updated map: for each CATEGORY_MAP key, find matching links.
            updated: dict[str, list[str]] = {}
            used_hrefs: set[str] = set()

            for display_name, keywords in self._CATEGORY_KEYWORDS.items():
                matches: list[str] = []
                for link in raw_links:
                    href_lower = link["href"].lower()
                    text_lower = link.get("text", "").lower()
                    combined = href_lower + " " + text_lower
                    if any(kw in combined for kw in keywords):
                        if link["href"] not in used_hrefs:
                            matches.append(link["href"])
                            used_hrefs.add(link["href"])
                if matches:
                    updated[display_name] = matches

            # For any CATEGORY_MAP key that got no match, keep the hardcoded URL as fallback.
            for display_name, paths in self.CATEGORY_MAP.items():
                if display_name not in updated:
                    updated[display_name] = list(paths)

            matched_count = sum(1 for k in updated if updated[k] != self.CATEGORY_MAP.get(k))
            print(f"[jiomart] Category discovery: {len(raw_links)} links found, "
                  f"{matched_count} categories refreshed, "
                  f"{len(updated) - matched_count} kept hardcoded fallback")
            return updated

        except Exception as e:
            print(f"[jiomart] Category discovery failed ({e}), using hardcoded fallback")
            return dict(self.CATEGORY_MAP)

    async def init_browser(self):
        """Use Firefox to bypass JioMart's Akamai bot detection (Chromium gets 403)."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.firefox.launch(
            headless=settings.HEADLESS,
        )
        self.context = await self.browser.new_context(
            user_agent=random.choice(FIREFOX_USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        self.page = await self.context.new_page()
        self.page.on("response", self._on_response)

    async def _on_response(self, response):
        """Capture JSON responses, including JioMart's /trex/search Google Retail format."""
        try:
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct and response.status == 200:
                body = await response.text()
                if len(body) > 100:
                    data = json.loads(body)
                    # Handle /trex/search Google Retail catalog format
                    if "trex/search" in url and "results" in data:
                        self._parse_trex_results(data["results"])
                    elif any(kw in body.lower() for kw in ["product", "price", "mrp", "name", "selling"]):
                        self._captured_responses.append({"url": url, "data": data})
        except Exception:
            pass

    def _parse_trex_results(self, results: list):
        """Parse JioMart's /trex/search API response (Google Retail catalog format)."""
        for item in results:
            try:
                product = item.get("product", {})

                # Filter: only keep grocery products
                cats = product.get("categories", [])
                if cats and not any("Groceries" in c or "groceries" in c for c in cats):
                    continue

                variants = product.get("variants", [])
                if not variants:
                    continue

                variant = variants[0]
                title = variant.get("title") or product.get("title", "")
                if not title:
                    continue

                brands = variant.get("brands", [])
                brand = brands[0] if brands else title.split()[0]

                # Parse price from buybox_mrp: "store|qty|seller||mrp|price||discount|disc_pct||rank|"
                attrs = variant.get("attributes", {})
                buybox = attrs.get("buybox_mrp", {}).get("text", [])
                price = 0.0
                mrp = None
                if buybox:
                    parts = buybox[0].split("|")
                    if len(parts) >= 6:
                        try:
                            mrp = float(parts[4]) if parts[4] else None
                            price = float(parts[5]) if parts[5] else 0.0
                        except (ValueError, IndexError):
                            pass

                if price <= 0:
                    continue

                # Category from "Category > Groceries > Cooking Essentials > Rice > Basmati Rice"
                cats = product.get("categories", [])
                category = None
                if cats:
                    cat_parts = cats[0].split(" > ")
                    category = cat_parts[-1] if len(cat_parts) > 1 else cats[0]

                # Image
                image = None
                images = variant.get("images", product.get("images", []))
                if images:
                    img = images[0]
                    if isinstance(img, dict):
                        image = img.get("uri") or img.get("url")
                    elif isinstance(img, str):
                        image = img

                pid = str(item.get("id", ""))
                if pid in self._seen_ids:
                    continue
                self._seen_ids.add(pid)

                self.products.append(Product(
                    product_name=title,
                    brand=brand,
                    price=price,
                    mrp=mrp,
                    unit=None,
                    category=category,
                    sub_category=None,
                    platform=self.platform_name,
                    pincode=self.pincode,
                    in_stock=True,
                    scraped_at=self.now_iso(),
                    image_url=image,
                ))
            except Exception:
                continue

    async def _extract_products_from_dom(self):
        """Extract products directly from JioMart's DOM (only on grocery pages)."""
        try:
            # Only extract from grocery pages to avoid jewelry/fashion items
            url = self.page.url
            if "/groceries" not in url and "/search/" not in url:
                return 0

            products = await self.page.evaluate("""() => {
                const cards = document.querySelectorAll('[class*="plp_product"], [class*="ProductCard"], [class*="product-card"]');
                const results = [];
                for (const card of cards) {
                    const text = card.innerText || '';
                    // Extract name from card text (first non-"Sponsored"/"Add" line)
                    const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 3);
                    let name = '';
                    for (const line of lines) {
                        if (!['Sponsored', 'Add', 'Add to Cart'].includes(line) && !line.startsWith('₹') && !line.includes('% OFF')) {
                            name = line;
                            break;
                        }
                    }
                    if (!name) continue;

                    // Extract prices
                    const priceMatch = text.match(/₹([\\d,.]+)/);
                    const price = priceMatch ? parseFloat(priceMatch[1].replace(',', '')) : 0;
                    const prices = [...text.matchAll(/₹([\\d,.]+)/g)].map(m => parseFloat(m[1].replace(',', '')));
                    const mrp = prices.length >= 2 ? prices[1] : null;

                    const img = card.querySelector('img')?.src || null;

                    if (price > 0) {
                        results.push({ name, price, mrp, img });
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
                    unit=None,
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
        """Override to add DOM extraction for JioMart."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._wait_for_network_settle(0.5, 3.0)
            await self._scroll_page(times=scroll_times, delay=0.8)

            # First try API response parsing (handled in _on_response)
            count = self._process_responses()

            # Also extract from DOM
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

    async def scrape_all(self) -> list[Product]:
        try:
            await self.init_browser()
            print(f"[jiomart] Starting scrape for pincode {self.pincode} (Firefox)")

            # Set pincode cookies
            await self.context.add_cookies([
                {"name": "pincode", "value": self.pincode, "domain": ".jiomart.com", "path": "/"},
                {"name": "address_pincode", "value": self.pincode, "domain": ".jiomart.com", "path": "/"},
            ])

            # Load homepage
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Try clicking "Select Location Manually" if visible
            try:
                sel_loc = self.page.locator('text="Select Location Manually"').first
                if await sel_loc.is_visible(timeout=3000):
                    await sel_loc.click()
                    await asyncio.sleep(2)
                    inp = self.page.locator('input[placeholder*="incode"], input[type="text"]').first
                    if await inp.is_visible(timeout=3000):
                        await inp.fill(self.pincode)
                        await asyncio.sleep(2)
                        try:
                            sug = self.page.locator('li, [role="option"]').first
                            if await sug.is_visible(timeout=3000):
                                await sug.click()
                                await asyncio.sleep(2)
                        except Exception:
                            await inp.press("Enter")
                            await asyncio.sleep(2)
            except Exception:
                pass

            # Auto-discover category URLs from the live groceries page.
            # This refreshes CATEGORY_MAP with current URLs so stale hardcoded
            # paths don't silently fail the entire scrape.
            live_category_map = await self._discover_categories(self.page)

            # Apply selected_categories filter to the live map
            if self.selected_categories and "all" not in self.selected_categories:
                categories = []
                for cat_name in self.selected_categories:
                    categories.extend(live_category_map.get(cat_name, []))
                if not categories:
                    # No match — fall back to all discovered categories
                    categories = [p for paths in live_category_map.values() for p in paths]
            else:
                categories = [p for paths in live_category_map.values() for p in paths]

            # Deep crawl categories + subcategories
            visited = set()
            queue = list(categories)
            consecutive_empty = 0
            print(f"[jiomart] Deep crawl starting with {len(queue)} seed URLs...")

            while queue and len(self.products) < self.max_products and len(visited) < 200:
                cat = queue.pop(0)
                if cat in visited:
                    continue
                visited.add(cat)

                url = cat if cat.startswith('http') else f"{self.base_url}{cat}"
                new = await self._visit_and_collect(url, scroll_times=6)

                if new > 0:
                    consecutive_empty = 0
                    print(f"[jiomart] [{len(visited)}] +{new} (total: {len(self.products)})")

                    # Pagination: visit page 2, 3, ... until empty
                    base_cat_url = url.split("?")[0]  # strip existing query params
                    for pg in range(2, 20):
                        if len(self.products) >= self.max_products:
                            break
                        pg_url = f"{base_cat_url}?page={pg}"
                        pg_new = await self._visit_and_collect(pg_url, scroll_times=3)
                        if pg_new > 0:
                            print(f"[jiomart]   page {pg}: +{pg_new} (total: {len(self.products)})")
                        else:
                            break  # no more pages
                else:
                    consecutive_empty += 1

                # Discover subcategory links
                try:
                    page_links = await self.page.evaluate("""
                        () => [...new Set(
                            [...document.querySelectorAll('a[href*="/c/groceries"]')]
                                .map(a => a.getAttribute('href'))
                                .filter(h => h)
                        )]
                    """)
                    for link in (page_links or []):
                        if link not in visited and link not in set(queue):
                            queue.append(link)
                except Exception:
                    pass

                if consecutive_empty >= 15 and len(visited) >= 10:
                    print(f"[jiomart] Early exit: {consecutive_empty} consecutive empty. {len(self.products)} products.")
                    break

            # Search
            if len(self.products) < self.max_products:
                await self._search_and_capture(
                    lambda term: f"{self.base_url}/search/{term}"
                )

            print(f"[jiomart] Final: {len(self.products)} products for {self.pincode}")
            return self.products[:self.max_products]
        finally:
            await self.close()
