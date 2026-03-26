import asyncio
import json

from app.models.product import Product
from app.scrapers.base_scraper import BaseScraper


class InstamartScraper(BaseScraper):
    platform_name = "instamart"
    base_url = "https://www.swiggy.com/instamart"

    CATEGORY_MAP = {
        "Fruits & Vegetables": [
            "/instamart/category/fruits-vegetables",
            "/instamart/collection/fresh-vegetables",
            "/instamart/collection/fresh-fruits",
        ],
        "Dairy, Bread & Eggs": [
            "/instamart/category/dairy-bread-eggs",
            "/instamart/collection/milk-curd-paneer",
        ],
        "Rice, Atta & Dal": ["/instamart/category/rice-atta-dal"],
        "Oils, Ghee & Masala": ["/instamart/category/oils-ghee-masala"],
        "Snacks & Biscuits": [
            "/instamart/category/snacks-biscuits",
            "/instamart/collection/chips-namkeen",
        ],
        "Beverages": ["/instamart/category/beverages"],
        "Tea & Coffee": ["/instamart/category/tea-coffee"],
        "Instant Food": ["/instamart/category/instant-food"],
        "Sweet Tooth": ["/instamart/category/sweet-tooth"],
        "Frozen Food": ["/instamart/category/frozen-food"],
        "Ice Cream": ["/instamart/category/ice-cream"],
        "Personal Care": ["/instamart/category/personal-care"],
        "Cleaning Essentials": ["/instamart/category/cleaning-essentials"],
        "Baby Care": ["/instamart/category/baby-care"],
        "Pet Care": ["/instamart/category/pet-care"],
        "Health & Wellness": ["/instamart/category/health-wellness"],
    }

    CATEGORY_SEARCH_MAP = {
        "Fruits & Vegetables": ["fruits", "vegetables"],
        "Dairy, Bread & Eggs": ["dairy", "breakfast"],
        "Rice, Atta & Dal": ["staples"],
        "Oils, Ghee & Masala": ["masala", "staples"],
        "Snacks & Biscuits": ["snacks"],
        "Beverages": ["beverages"],
        "Tea & Coffee": ["tea_coffee"],
        "Instant Food": ["breakfast", "frozen"],
        "Sweet Tooth": ["sweet", "snacks"],
        "Frozen Food": ["frozen"],
        "Ice Cream": ["frozen"],
        "Personal Care": ["personal_care"],
        "Cleaning Essentials": ["cleaning"],
        "Baby Care": ["baby_health"],
        "Pet Care": ["pet_care"],
        "Health & Wellness": ["baby_health"],
    }

    FALLBACK_CATEGORY_PATHS = [path for paths in CATEGORY_MAP.values() for path in paths]

    # Uses Chromium from BaseScraper (Firefox gets 403 on swiggy.com WAF)
    # NOTE: Swiggy Instamart's web version does NOT serve product data (prices/MRP).
    # The web APIs only return category navigation and search suggestions.
    # Product listings are exclusively served through the mobile app.
    # This scraper makes best-effort attempts via API + DOM extraction.

    async def _on_response(self, response):
        """Capture JSON responses, including Swiggy's widget-based API format."""
        try:
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct and response.status == 200:
                body = await response.text()
                if len(body) > 100:
                    # Capture Swiggy API responses specifically
                    if "swiggy.com/api" in url:
                        try:
                            data = json.loads(body)
                            self._captured_responses.append({"url": url, "data": data})
                            # Parse Swiggy widget products inline
                            self._parse_swiggy_widgets(data)
                        except json.JSONDecodeError:
                            pass
                    elif any(kw in body.lower() for kw in ["product", "price", "mrp", "name", "selling"]):
                        try:
                            data = json.loads(body)
                            self._captured_responses.append({"url": url, "data": data})
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass

    def _parse_swiggy_widgets(self, data, depth=0):
        """Parse Swiggy's card/widget format for product data."""
        if depth > 10:
            return
        if isinstance(data, dict):
            # Check for product-like structure with price fields
            has_name = any(k in data for k in ["displayName", "name", "productName", "display_name"])
            has_price = any(k in data for k in ["price", "mrp", "offer_price", "sellingPrice",
                                                 "finalPrice", "selling_price"])
            if has_name and has_price:
                name = ""
                for key in ["displayName", "display_name", "name", "productName"]:
                    val = data.get(key)
                    if val and isinstance(val, str) and len(val) > 1:
                        name = val.strip()
                        break
                if not name:
                    return

                price = 0.0
                for key in ["price", "offer_price", "sellingPrice", "selling_price", "finalPrice"]:
                    val = data.get(key)
                    if val:
                        try:
                            price = float(str(val).replace(",", "").replace("₹", "").strip())
                            # Swiggy prices are sometimes in paise
                            if price > 50000:
                                price /= 100
                            if price > 0:
                                break
                        except (ValueError, TypeError):
                            continue

                mrp = None
                for key in ["mrp", "marked_price", "maxPrice"]:
                    val = data.get(key)
                    if val:
                        try:
                            mrp = float(str(val).replace(",", "").replace("₹", "").strip())
                            if mrp > 50000:
                                mrp /= 100
                            if mrp > 0:
                                break
                        except (ValueError, TypeError):
                            continue

                if price > 0:
                    pid = str(data.get("id", "")) or name
                    if pid not in self._seen_ids:
                        self._seen_ids.add(pid)

                        brand = data.get("brand", data.get("brandName", name.split()[0] if name else "Unknown"))
                        unit = data.get("unit", data.get("weight", data.get("quantity", data.get("pack_desc"))))
                        category = data.get("category", data.get("categoryName"))
                        image = data.get("image_url", data.get("imageUrl", data.get("image")))
                        if not image:
                            images = data.get("images", [])
                            if images and isinstance(images, list):
                                img = images[0]
                                image = img if isinstance(img, str) else img.get("url", img.get("src")) if isinstance(img, dict) else None

                        self.products.append(Product(
                            product_name=name,
                            brand=str(brand).strip() if brand else name.split()[0],
                            price=price,
                            mrp=mrp if mrp and mrp != price else None,
                            unit=str(unit).strip() if unit else None,
                            category=str(category).strip() if category else None,
                            sub_category=None,
                            platform=self.platform_name,
                            pincode=self.pincode,
                            in_stock=True,
                            scraped_at=self.now_iso(),
                            image_url=image,
                        ))

            for val in data.values():
                self._parse_swiggy_widgets(val, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self._parse_swiggy_widgets(item, depth + 1)

    async def _extract_products_from_dom(self) -> int:
        """Extract products from Swiggy Instamart's DOM."""
        try:
            products = await self.page.evaluate(r"""() => {
                const results = [];
                const seen = new Set();
                const allEls = document.querySelectorAll('div, a');
                for (const el of allEls) {
                    const text = el.innerText?.trim() || '';
                    if (!text.includes('\u20B9') || text.length < 15 || text.length > 500) continue;
                    const img = el.querySelector('img');
                    if (!img) continue;
                    const cc = el.children.length;
                    if (cc < 2 || cc > 20) continue;
                    let isLeaf = true;
                    for (const child of el.children) {
                        const ct = child.innerText?.trim() || '';
                        if (ct.includes('\u20B9') && child.querySelector('img') && ct.length > 15 && ct.length < 500) {
                            isLeaf = false;
                            break;
                        }
                    }
                    if (!isLeaf) continue;

                    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                    let name = '', unit = null;
                    const prices = [];
                    const skipWords = ['ADD', 'Add', 'Sold Out', 'Out of Stock', 'OFF', 'Offer',
                                       'Bestseller', 'New', 'Added'];
                    for (const line of lines) {
                        const priceMatch = line.match(/\u20B9\s?([\d,]+)/);
                        if (priceMatch) {
                            prices.push(parseFloat(priceMatch[1].replace(/,/g, '')));
                        } else if (!skipWords.some(w => line === w)
                                   && !line.match(/^\d+% off$/i)
                                   && !line.match(/^\d+\.\d+$/)
                                   && line.length > 2 && line.length < 200) {
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

                    if (name && name.length > 3 && prices.length > 0 && !seen.has(name)) {
                        seen.add(name);
                        const price = Math.min(...prices);
                        const mrp = prices.length >= 2 ? Math.max(...prices) : null;
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
        """Override to add DOM extraction for Instamart."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._wait_for_network_settle(0.5, 3.0)
            await self._scroll_page(times=scroll_times, delay=0.8)

            # Try API response parsing (handled in _on_response + _parse_swiggy_widgets)
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

    async def _set_swiggy_location(self):
        """Set Swiggy location via cookies and localStorage."""
        location_data = json.dumps({
            "lat": self.lat, "lng": self.lng,
            "address": f"Pincode {self.pincode}", "pincode": self.pincode
        })

        await self.context.add_cookies([
            {"name": "lat", "value": str(self.lat), "domain": ".swiggy.com", "path": "/"},
            {"name": "lng", "value": str(self.lng), "domain": ".swiggy.com", "path": "/"},
            {"name": "userLocation", "value": location_data, "domain": ".swiggy.com", "path": "/"},
            {"name": "addressId", "value": "", "domain": ".swiggy.com", "path": "/"},
        ])

        try:
            escaped = json.dumps(location_data)  # double-escape for JS string literal
            await self.page.evaluate(f"""() => {{
                localStorage.setItem('lat', '{self.lat}');
                localStorage.setItem('lng', '{self.lng}');
                localStorage.setItem('userLocation', {escaped});
                localStorage.setItem('address', JSON.stringify({{
                    lat: {self.lat}, lng: {self.lng},
                    pincode: '{self.pincode}'
                }}));
            }}""")
        except Exception:
            pass  # localStorage may fail on 403 pages; cookies are the primary mechanism

    async def _discover_categories(self):
        """Discover category/collection links from the page."""
        filtered_paths = set(self._get_filtered_category_paths())
        categories = []
        try:
            page_cats = await self.page.evaluate("""
                () => [...document.querySelectorAll('a')]
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && h.includes('/instamart/') &&
                            (h.includes('/category/') || h.includes('/collection/')))
            """)
            discovered = list(set(page_cats or []))
            if self.selected_categories and "all" not in self.selected_categories:
                categories = [c for c in discovered if c in filtered_paths]
            else:
                categories = discovered
        except Exception:
            pass

        if len(categories) < 3:
            categories = list(filtered_paths) if filtered_paths else self.FALLBACK_CATEGORY_PATHS

        return categories[:30]

    async def scrape_all(self) -> list[Product]:
        try:
            await self.init_browser()
            print(f"[instamart] Starting scrape for pincode {self.pincode} (Chromium)")

            # Set location cookies BEFORE first navigation
            location_data = json.dumps({
                "lat": self.lat, "lng": self.lng,
                "address": f"Pincode {self.pincode}", "pincode": self.pincode
            })
            await self.context.add_cookies([
                {"name": "lat", "value": str(self.lat), "domain": ".swiggy.com", "path": "/"},
                {"name": "lng", "value": str(self.lng), "domain": ".swiggy.com", "path": "/"},
                {"name": "userLocation", "value": location_data, "domain": ".swiggy.com", "path": "/"},
                {"name": "addressId", "value": "", "domain": ".swiggy.com", "path": "/"},
            ])

            # Navigate to Swiggy first to pass WAF challenge
            try:
                await self.page.goto("https://www.swiggy.com", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(3)
            except Exception:
                pass

            # Set localStorage now that we have a page context
            await self._set_swiggy_location()

            # Navigate to Instamart
            try:
                await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                # Handle redirect: swiggy.com sometimes redirects /instamart back to /
                await asyncio.sleep(2)
                if "/instamart" not in self.page.url:
                    await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(3)

            # Process any captured API responses from page load
            self._process_responses()
            dom_count = await self._extract_products_from_dom()
            print(f"[instamart] Homepage: {len(self.products)} products")

            # Phase 1: Search first (most reliable)
            await self._search_and_capture(
                lambda term: f"https://www.swiggy.com/instamart/search?custom_back=true&query={term}"
            )
            print(f"[instamart] After search: {len(self.products)} products")

            # Phase 2: Deep crawl categories + subcategories
            if len(self.products) < self.max_products:
                seed_categories = await self._discover_categories()
                print(f"[instamart] Discovered {len(seed_categories)} seed categories, crawling...")

                visited = set()
                queue = list(seed_categories)
                consecutive_empty = 0

                while queue and len(self.products) < self.max_products and len(visited) < 200:
                    cat = queue.pop(0)
                    if cat in visited:
                        continue
                    visited.add(cat)

                    url = cat if cat.startswith('http') else f"https://www.swiggy.com{cat}"
                    new = await self._visit_and_collect(url, scroll_times=6)

                    if new > 0:
                        consecutive_empty = 0
                        print(f"[instamart] [{len(visited)}] +{new} (total: {len(self.products)})")
                    else:
                        consecutive_empty += 1

                    # Discover subcategory links
                    try:
                        page_links = await self.page.evaluate("""
                            () => [...document.querySelectorAll('a')]
                                .map(a => a.getAttribute('href'))
                                .filter(h => h && h.includes('/instamart/') &&
                                        (h.includes('/category/') || h.includes('/collection/')))
                        """)
                        for link in (page_links or []):
                            if link not in visited and link not in set(queue):
                                queue.append(link)
                    except Exception:
                        pass

                    if consecutive_empty >= 15 and len(visited) >= 10:
                        print(f"[instamart] Early exit: {consecutive_empty} consecutive empty. {len(self.products)} products.")
                        break

            # Fallback: HTML extraction
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

            print(f"[instamart] Final: {len(self.products)} products for {self.pincode}")
            return self.products[:self.max_products]
        finally:
            await self.close()
