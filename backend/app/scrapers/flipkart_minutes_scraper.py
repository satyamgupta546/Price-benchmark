import asyncio
import re

from app.models.product import Product
from app.scrapers.base_scraper import BaseScraper


class FlipkartMinutesScraper(BaseScraper):
    platform_name = "flipkart_minutes"
    base_url = "https://www.flipkart.com"

    CATEGORY_MAP = {
        "Grocery Supermart": ["/grocery-supermart-store"],
        "Fruits & Vegetables": ["/grocery/fruits-and-vegetables/pr?sid=eat"],
        "Dairy & Bakery": ["/grocery/dairy-and-bakery/pr?sid=eat"],
        "Staples": ["/grocery/staples/pr?sid=eat"],
        "Snacks & Beverages": ["/grocery/snacks-and-beverages/pr?sid=eat"],
        "Packaged Food": ["/grocery/packaged-food/pr?sid=eat"],
        "Household Care": ["/grocery/household-care/pr?sid=eat"],
        "Personal Care": ["/grocery/personal-care/pr?sid=eat"],
    }

    CATEGORY_SEARCH_MAP = {
        "Grocery Supermart": ["staples", "dairy", "snacks"],
        "Fruits & Vegetables": ["fruits", "vegetables"],
        "Dairy & Bakery": ["dairy", "breakfast"],
        "Staples": ["staples", "masala"],
        "Snacks & Beverages": ["snacks", "beverages", "tea_coffee"],
        "Packaged Food": ["breakfast", "frozen", "snacks"],
        "Household Care": ["cleaning", "kitchen_home"],
        "Personal Care": ["personal_care"],
    }

    async def _extract_products_from_dom(self) -> int:
        """Extract products from Flipkart's server-rendered grocery pages."""
        try:
            products = await self.page.evaluate("""() => {
                const results = [];
                // Flipkart grocery products have img[src*="rukminim"] and price elements
                // Try multiple card selector patterns
                const selectors = [
                    '[data-id]',  // product cards with data-id
                    'div[class*="tUxRFH"]',  // common Flipkart product card class
                    'div[class*="slAVV4"]',  // another product card class
                ];

                // Fallback: find all divs that contain both an image and a price
                const allDivs = document.querySelectorAll('div');
                const cards = [];
                for (const div of allDivs) {
                    const hasImg = div.querySelector('img[src*="rukminim"]');
                    const text = div.innerText || '';
                    const hasPrice = text.includes('₹');
                    const childCount = div.children.length;
                    // Card-like: has image, has price, reasonable size
                    if (hasImg && hasPrice && childCount >= 2 && childCount <= 20 &&
                        text.length > 20 && text.length < 500) {
                        cards.push(div);
                    }
                }

                // Dedupe by keeping smallest enclosing card
                const seen = new Set();
                for (const card of cards) {
                    const text = card.innerText?.trim();
                    if (!text || seen.has(text)) continue;
                    seen.add(text);

                    const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                    // Find product name (first non-price, non-discount line)
                    let name = '';
                    for (const line of lines) {
                        if (!line.startsWith('₹') && !line.includes('% off') && !line.includes('OFF') &&
                            !line.includes('Add to') && line.length > 3 && line.length < 200) {
                            name = line;
                            break;
                        }
                    }
                    if (!name) continue;

                    // Extract prices
                    const prices = [...text.matchAll(/₹([\\d,]+)/g)].map(m => parseFloat(m[1].replace(/,/g, '')));
                    const price = prices.length > 0 ? Math.min(...prices) : 0;
                    const mrp = prices.length > 1 ? Math.max(...prices) : null;

                    const img = card.querySelector('img[src*="rukminim"]')?.src || null;

                    if (price > 0 && name.length > 3) {
                        results.push({ name, price, mrp: mrp !== price ? mrp : null, img });
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
        """Override to add DOM extraction for Flipkart grocery."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._wait_for_network_settle(0.5, 3.0)
            await self._scroll_page(times=scroll_times, delay=0.8)

            # Try API response parsing first
            count = self._process_responses()

            # Also extract from DOM (Flipkart grocery is mostly server-rendered)
            dom_count = await self._extract_products_from_dom()
            count += dom_count

            await self._report_progress()
            return count
        except Exception as e:
            print(f"[{self.platform_name}] Visit {url} error: {e}")
            return 0

    async def _search_and_capture(self, search_url_fn):
        """Override to add DOM extraction for Flipkart grocery search results."""
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
                new = await self._visit_and_collect(url, scroll_times=5)

                after = len(self.products)
                if after > before:
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
            except Exception as e:
                print(f"[{self.platform_name}] Search '{term}' error: {e}")
                consecutive_empty += 1
                continue

    async def _set_grocery_pincode(self) -> bool:
        """Set pincode for Flipkart grocery via the verification form."""
        try:
            # Go to grocery search — this triggers the pincode verification page
            await self.page.goto(
                f"{self.base_url}/search?q=grocery&marketplace=GROCERY",
                wait_until="domcontentloaded", timeout=30000,
            )
            await asyncio.sleep(2)

            # Fill the "Enter pincode" input using press_sequentially
            # (fill() doesn't trigger React onChange — must type char by char)
            pin_input = self.page.locator('input[placeholder="Enter pincode"], input[name="pincode"]').first
            if await pin_input.is_visible(timeout=5000):
                await pin_input.click()
                await pin_input.press_sequentially(self.pincode, delay=100)
                await asyncio.sleep(1)
                await pin_input.press("Enter")
                await asyncio.sleep(3)
                print(f"[flipkart_minutes] Pincode {self.pincode} set via grocery form")
                return True
        except Exception as e:
            print(f"[flipkart_minutes] Grocery pincode form not found: {e}")

        return False

    async def _set_delivery_location(self) -> bool:
        """Set delivery location via the header location picker."""
        try:
            # Click "Select delivery location" link in header
            loc_link = self.page.locator('text="Select delivery location"').first
            if await loc_link.is_visible(timeout=3000):
                await loc_link.click()
                await asyncio.sleep(2)

                # Type pincode in the location search input
                search_input = self.page.locator('input[placeholder*="Search by area"]').first
                if await search_input.is_visible(timeout=3000):
                    await search_input.fill(self.pincode)
                    await asyncio.sleep(3)

                    # Click first suggestion
                    for sug_sel in [
                        'li:first-child',
                        '[role="option"]:first-child',
                        'div[class*="suggestion"]:first-child',
                    ]:
                        try:
                            sug = self.page.locator(sug_sel).first
                            if await sug.is_visible(timeout=3000):
                                await sug.click()
                                await asyncio.sleep(2)
                                print(f"[flipkart_minutes] Location set via header picker")
                                return True
                        except Exception:
                            continue

                    await search_input.press("Enter")
                    await asyncio.sleep(2)
                    return True
        except Exception:
            pass
        return False

    async def scrape_all(self) -> list[Product]:
        try:
            await self.init_browser()
            print(f"[flipkart_minutes] Starting scrape for pincode {self.pincode}")

            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            # Dismiss login popup
            try:
                close = self.page.locator('button:has-text("✕")').first
                if await close.is_visible(timeout=3000):
                    await close.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Set delivery location via header
            await self._set_delivery_location()

            # Set grocery-specific pincode via the verification form
            pincode_set = await self._set_grocery_pincode()

            if not pincode_set:
                print(f"[flipkart_minutes] Warning: could not set grocery pincode. Products may be limited.")

            # Search for grocery items
            await self._search_and_capture(
                lambda term: f"{self.base_url}/search?q={term}&marketplace=GROCERY"
            )

            # Deep crawl Flipkart grocery categories + subcategories
            minutes_paths = self._get_filtered_category_paths()
            visited = set()
            queue = list(minutes_paths)
            consecutive_empty = 0

            while queue and len(self.products) < self.max_products and len(visited) < 200:
                path = queue.pop(0)
                if path in visited:
                    continue
                visited.add(path)

                url = f"{self.base_url}{path}" if path.startswith('/') else path
                new = await self._visit_and_collect(url, scroll_times=6)

                if new > 0:
                    consecutive_empty = 0
                    print(f"[flipkart_minutes] [{len(visited)}] +{new} (total: {len(self.products)})")
                else:
                    consecutive_empty += 1

                # Discover subcategory links
                try:
                    page_links = await self.page.evaluate("""
                        () => [...document.querySelectorAll('a[href*="/grocery"]')]
                            .map(a => a.getAttribute('href'))
                            .filter(h => h && h.includes('/grocery'))
                    """)
                    for link in (page_links or []):
                        if link not in visited and link not in set(queue):
                            queue.append(link)
                except Exception:
                    pass

                if consecutive_empty >= 15 and len(visited) >= 8:
                    break

            print(f"[flipkart_minutes] Final: {len(self.products)} products for {self.pincode}")
            return self.products[:self.max_products]
        finally:
            await self.close()
