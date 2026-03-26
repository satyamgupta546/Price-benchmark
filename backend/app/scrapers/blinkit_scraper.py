import asyncio
import json

from app.models.product import Product
from app.scrapers.base_scraper import BaseScraper


class BlinkitScraper(BaseScraper):
    platform_name = "blinkit"
    base_url = "https://blinkit.com"

    CATEGORY_MAP = {
        "Paan Corner": ["/cn/paan-corner/cid/21/1365"],
        "Dairy, Bread & Eggs": [
            "/cn/dairy-bread-eggs/cid/12/1028",
            "/cn/milk/cid/12/1029", "/cn/bread/cid/12/1030",
            "/cn/eggs/cid/12/1037", "/cn/paneer-curd/cid/12/1031",
            "/cn/butter-cheese/cid/12/1034",
        ],
        "Fruits & Vegetables": [
            "/cn/vegetables-fruits/cid/1/2", "/cn/fruits/cid/1/3",
            "/cn/exotic-fruits-veggies/cid/1/62", "/cn/fresh-vegetables/cid/1/2",
            "/cn/herbs-seasonings/cid/1/691",
        ],
        "Snacks & Munchies": [
            "/cn/snacks-munchies/cid/7/930", "/cn/chips-crisps/cid/7/931",
            "/cn/nachos/cid/7/945",
        ],
        "Cold Drinks & Juices": [
            "/cn/cold-drinks-juices/cid/5/855", "/cn/soft-drinks/cid/5/855",
            "/cn/juices/cid/5/870", "/cn/water/cid/5/886", "/cn/energy-drinks/cid/5/895",
        ],
        "Breakfast & Instant Food": [
            "/cn/breakfast-instant-food/cid/14/1117", "/cn/breakfast-cereals/cid/14/1117",
            "/cn/noodles-pasta/cid/14/1118", "/cn/ready-to-cook/cid/14/1127",
            "/cn/ready-to-eat/cid/14/1128",
        ],
        "Sweet Tooth": [
            "/cn/sweet-tooth/cid/13/1068", "/cn/chocolates/cid/13/1068",
            "/cn/desserts/cid/13/1093", "/cn/ice-creams/cid/13/1098",
            "/cn/indian-sweets/cid/13/1113",
        ],
        "Bakery & Biscuits": [
            "/cn/bakery-biscuits/cid/3/745", "/cn/biscuits-cookies/cid/3/745",
            "/cn/rusks-wafers/cid/3/807", "/cn/bakery/cid/3/810",
        ],
        "Tea, Coffee & Health Drink": [
            "/cn/tea-coffee-health-drink/cid/8/938", "/cn/tea/cid/8/938",
            "/cn/coffee/cid/8/939", "/cn/health-drink/cid/8/943",
        ],
        "Atta, Rice & Dal": [
            "/cn/atta-rice-dal/cid/9/946", "/cn/atta-flours/cid/9/946",
            "/cn/rice-products/cid/9/964", "/cn/dals-pulses/cid/9/977",
            "/cn/organic-rice/cid/9/965", "/cn/organic-atta/cid/9/947",
            "/cn/organic-dals/cid/9/978",
        ],
        "Masala, Oil & More": [
            "/cn/masala-oil-more/cid/10/979", "/cn/salt-sugar-jaggery/cid/10/1008",
            "/cn/cooking-oil/cid/10/989", "/cn/masalas-spices/cid/10/979",
            "/cn/whole-spices/cid/10/985", "/cn/blended-masalas/cid/10/980",
        ],
        "Sauces & Spreads": [
            "/cn/sauces-spreads/cid/11/1009", "/cn/ketchup-sauce/cid/11/1009",
            "/cn/spreads/cid/11/1024", "/cn/honey/cid/11/1021",
        ],
        "Chicken, Meat & Fish": ["/cn/chicken-meat-fish/cid/4/825"],
        "Organic & Healthy Living": [
            "/cn/organic-healthy-living/cid/15/1132", "/cn/organic-staples/cid/15/1132",
            "/cn/dry-fruits/cid/15/1152",
        ],
        "Baby Care": [
            "/cn/baby-care/cid/16/1175", "/cn/diapers-wipes/cid/16/1175",
            "/cn/baby-food/cid/16/1184",
        ],
        "Pharma & Wellness": ["/cn/pharma-wellness/cid/17/1193"],
        "Cleaning Essentials": [
            "/cn/cleaning-essentials/cid/18/1242", "/cn/detergents/cid/18/1242",
            "/cn/dishwash/cid/18/1250", "/cn/floor-cleaners/cid/18/1254",
        ],
        "Home & Office": ["/cn/home-office/cid/19/1269"],
        "Personal Care": [
            "/cn/personal-care/cid/20/1285", "/cn/bath-body/cid/20/1285",
            "/cn/hair-care/cid/20/1296", "/cn/skin-care/cid/20/1309",
            "/cn/oral-care/cid/20/1321",
        ],
        "Pet Care": ["/cn/pet-care/cid/22/1393"],
    }

    CATEGORY_SEARCH_MAP = {
        "Paan Corner": ["paan"],
        "Dairy, Bread & Eggs": ["dairy", "breakfast"],
        "Fruits & Vegetables": ["fruits", "vegetables"],
        "Snacks & Munchies": ["snacks"],
        "Cold Drinks & Juices": ["beverages"],
        "Breakfast & Instant Food": ["breakfast", "frozen"],
        "Sweet Tooth": ["sweet", "frozen"],
        "Bakery & Biscuits": ["snacks", "breakfast"],
        "Tea, Coffee & Health Drink": ["tea_coffee", "baby_health"],
        "Atta, Rice & Dal": ["staples"],
        "Masala, Oil & More": ["masala", "staples"],
        "Sauces & Spreads": ["masala"],
        "Chicken, Meat & Fish": ["non_veg"],
        "Organic & Healthy Living": ["dry_fruits", "staples"],
        "Baby Care": ["baby_health"],
        "Pharma & Wellness": ["baby_health"],
        "Cleaning Essentials": ["cleaning"],
        "Home & Office": ["kitchen_home"],
        "Personal Care": ["personal_care"],
        "Pet Care": ["pet_care"],
    }

    @staticmethod
    def _extract_cids(paths: list[str]) -> set[str]:
        """Extract category IDs (e.g. '9' from '/cn/.../cid/9/946') from paths."""
        import re
        cids = set()
        for p in paths:
            m = re.search(r'/cid/(\d+)/', p)
            if m:
                cids.add(m.group(1))
        return cids

    async def _discover_links_on_page(self) -> list[str]:
        """Extract all /cn/ links from the current page."""
        try:
            links = await self.page.evaluate("""
                () => [...document.querySelectorAll('a[href*="/cn/"]')]
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && h.startsWith('/cn/'))
            """)
            return list(set(links or []))
        except Exception:
            return []

    async def scrape_all(self) -> list[Product]:
        try:
            await self.init_browser()
            print(f"[blinkit] Starting scrape for pincode {self.pincode} ({self.lat}, {self.lng})")

            # Load homepage first to establish origin for localStorage
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1)

            # Set location via localStorage (Blinkit reads coords from this JSON)
            location_data = json.dumps({
                "coords": {
                    "isDefault": False,
                    "lat": self.lat,
                    "lon": self.lng,
                    "locality": "Selected Location",
                    "id": None,
                    "isTopCity": False,
                    "cityName": "Selected",
                    "landmark": None,
                    "addressId": None,
                }
            })
            await self.page.evaluate(f"() => localStorage.setItem('location', {json.dumps(location_data)})")

            # Set cookies (Blinkit uses gr_1_lon, NOT gr_1_lng)
            await self.context.add_cookies([
                {"name": "__pincode", "value": self.pincode, "domain": ".blinkit.com", "path": "/"},
                {"name": "gr_1_lat", "value": str(self.lat), "domain": ".blinkit.com", "path": "/"},
                {"name": "gr_1_lon", "value": str(self.lng), "domain": ".blinkit.com", "path": "/"},
            ])

            # Reload to pick up new location
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Seed URLs: filtered CATEGORY_MAP paths + homepage links
            seed_paths = set(self._get_filtered_category_paths())
            homepage_links = await self._discover_links_on_page()

            if self.selected_categories and "all" not in self.selected_categories:
                # When specific categories selected, only use CATEGORY_MAP paths
                queue = list(seed_paths)
            else:
                queue = list(seed_paths | set(homepage_links))

            visited = set()
            consecutive_empty = 0
            max_pages = 300  # safety cap

            # When specific categories selected, extract allowed cids to scope BFS
            allowed_cids = self._extract_cids(list(seed_paths)) if (
                self.selected_categories and "all" not in self.selected_categories
            ) else None

            print(f"[blinkit] Deep crawl starting with {len(queue)} seed URLs"
                  f"{f' (cids: {allowed_cids})' if allowed_cids else ''}...")

            # --- Phase 1: Deep category crawl (BFS) ---
            # Visit each category, discover subcategory links, visit those too
            while queue and len(self.products) < self.max_products and len(visited) < max_pages:
                cat_path = queue.pop(0)
                if cat_path in visited:
                    continue
                visited.add(cat_path)

                url = f"{self.base_url}{cat_path}" if cat_path.startswith('/') else cat_path
                new = await self._visit_and_collect(url, scroll_times=8)

                if new > 0:
                    consecutive_empty = 0
                    print(f"[blinkit] [{len(visited)}/{len(visited)+len(queue)}] +{new} products (total: {len(self.products)}) from {cat_path[:60]}")
                else:
                    consecutive_empty += 1

                # Discover subcategory links from this page and enqueue new ones.
                # When filtering by category, only follow links with matching cids
                # to avoid drifting into unrelated categories via sidebar nav.
                page_links = await self._discover_links_on_page()
                for link in page_links:
                    if link not in visited and link not in set(queue):
                        if allowed_cids:
                            link_cids = self._extract_cids([link])
                            if link_cids and link_cids & allowed_cids:
                                queue.append(link)
                        else:
                            queue.append(link)

                # Only early-exit if we've visited 20+ pages and keep hitting empties
                if consecutive_empty >= 15 and len(visited) >= 20:
                    print(f"[blinkit] Early exit from crawl: {consecutive_empty} consecutive empty pages. "
                          f"Visited {len(visited)} pages, {len(self.products)} products.")
                    break

            print(f"[blinkit] Deep crawl done: visited {len(visited)} pages, {len(self.products)} products. Now searching...")

            # --- Phase 2: Search to fill gaps ---
            if len(self.products) < self.max_products:
                await self._search_and_capture(
                    lambda term: f"{self.base_url}/s/?q={term}"
                )

            print(f"[blinkit] Final: {len(self.products)} products for {self.pincode}")
            return self.products[:self.max_products]
        finally:
            await self.close()
