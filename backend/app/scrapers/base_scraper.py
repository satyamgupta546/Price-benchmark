import asyncio
import json
import random
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from app.config import settings
from app.models.product import Product

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# Indian pincode prefix → approximate (lat, lng)
PINCODE_COORDS = {
    "11": (28.6139, 77.2090), "12": (28.4595, 77.0266), "13": (30.7333, 76.7794),
    "14": (30.7333, 76.7794), "15": (32.7266, 74.8570), "16": (31.1048, 77.1734),
    "17": (31.1048, 77.1734), "18": (34.0837, 74.7973), "19": (34.0837, 74.7973),
    "20": (26.8467, 80.9462), "21": (25.4358, 81.8463),
    "22": (26.4499, 80.3319), "23": (27.1767, 78.0081), "24": (28.9845, 77.7064),
    "25": (28.6692, 77.4538), "26": (26.8467, 80.9462), "27": (26.8467, 80.9462),
    "28": (26.4499, 80.3319), "29": (26.9124, 75.7873),
    "30": (26.9124, 75.7873), "31": (28.0229, 73.3119),
    "32": (26.2389, 73.0243), "33": (24.5854, 73.7125), "34": (25.1743, 75.8554),
    "35": (25.1743, 75.8554), "36": (23.2599, 77.4126), "37": (21.1458, 79.0882),
    "38": (23.0225, 72.5714), "39": (21.1702, 72.8311),
    "40": (19.0760, 72.8777), "41": (18.5204, 73.8567),
    "42": (19.8762, 75.3433), "43": (20.9374, 77.7796), "44": (21.1458, 79.0882),
    "45": (22.7196, 75.8577), "46": (23.2599, 77.4126), "47": (23.1815, 79.9864),
    "48": (23.1815, 79.9864), "49": (21.2514, 81.6296),
    "50": (17.3850, 78.4867), "51": (17.3850, 78.4867), "52": (15.8281, 78.0373),
    "53": (17.6868, 83.2185), "54": (16.5062, 80.6480), "55": (15.4909, 78.4867),
    "56": (12.9716, 77.5946), "57": (15.3647, 75.1240),
    "58": (15.3647, 75.1240), "59": (15.8497, 74.4977),
    "60": (13.0827, 80.2707), "61": (10.7905, 78.7047), "62": (9.9252, 78.1198),
    "63": (11.0168, 76.9558), "64": (11.0168, 76.9558), "65": (8.7642, 77.6990),
    "66": (11.8745, 75.3704), "67": (11.2588, 75.7804), "68": (9.9312, 76.2673),
    "69": (8.5241, 76.9366),
    "70": (22.5726, 88.3639), "71": (22.5726, 88.3639),
    "72": (22.5726, 88.3639), "73": (22.5726, 88.3639), "74": (22.5726, 88.3639),
    "75": (20.2961, 85.8245), "76": (20.2961, 85.8245), "77": (26.1445, 91.7362),
    "78": (26.1445, 91.7362), "79": (23.9408, 91.9882),
    "80": (25.6093, 85.1376), "81": (25.6093, 85.1376), "82": (23.3441, 85.3096),
    "83": (23.3441, 85.3096), "84": (26.1542, 86.0614), "85": (25.2425, 86.9842),
}


def get_coords(pincode: str) -> tuple:
    prefix = pincode[:2] if len(pincode) >= 2 else ""
    return PINCODE_COORDS.get(prefix, (28.6139, 77.2090))


class BaseScraper(ABC):
    platform_name: str = ""
    base_url: str = ""

    # Overridden by each platform scraper: display name → list of URL paths
    CATEGORY_MAP: dict[str, list[str]] = {}
    # Overridden by each platform scraper: display name → list of search term group keys
    CATEGORY_SEARCH_MAP: dict[str, list[str]] = {}

    SEARCH_TERMS_BY_CATEGORY = {
        "staples": [
            "rice", "atta", "dal", "oil", "sugar", "salt", "flour", "wheat", "maida", "sooji",
            "poha", "besan", "chana dal", "moong dal", "masoor dal", "rajma", "toor dal", "urad dal",
            "basmati rice", "mustard oil", "sunflower oil", "refined oil", "jaggery", "sago",
        ],
        "dairy": [
            "milk", "curd", "paneer", "butter", "cheese", "ghee", "cream", "yogurt", "dahi",
            "lassi", "buttermilk", "milk powder", "condensed milk",
        ],
        "fruits": [
            "banana", "apple", "orange", "mango", "grapes", "papaya", "watermelon", "pomegranate",
            "guava", "kiwi", "pineapple", "lemon", "coconut", "litchi", "pear",
        ],
        "vegetables": [
            "onion", "potato", "tomato", "spinach", "capsicum", "carrot", "cucumber", "ginger",
            "garlic", "cabbage", "cauliflower", "brinjal", "ladyfinger", "peas", "beans",
            "mushroom", "corn", "beetroot", "radish", "pumpkin", "bitter gourd", "bottle gourd",
            "green chilli", "coriander leaves", "curry leaves", "mint",
        ],
        "snacks": [
            "chips", "biscuit", "namkeen", "cookies", "chocolate", "candy", "cake", "rusk",
            "popcorn", "makhana", "mixture", "wafer", "kurkure", "lays",
        ],
        "beverages": [
            "juice", "water", "cold drink", "cola", "soda", "energy drink", "coconut water",
            "milkshake", "soft drink", "mineral water", "aam panna",
        ],
        "breakfast": [
            "bread", "maggi", "noodles", "oats", "cornflakes", "muesli", "cereal", "jam",
            "honey", "peanut butter", "nutella", "spread", "pasta", "vermicelli", "upma mix",
            "idli mix", "dosa mix", "pancake mix",
        ],
        "tea_coffee": [
            "tea", "coffee", "green tea", "filter coffee", "tea bags", "instant coffee",
        ],
        "masala": [
            "turmeric", "chilli powder", "garam masala", "cumin", "coriander powder", "pepper",
            "ketchup", "sauce", "mayonnaise", "vinegar", "pickle", "papad", "soy sauce",
            "mustard sauce",
        ],
        "non_veg": [
            "egg", "chicken", "mutton", "fish", "prawn", "chicken breast",
        ],
        "personal_care": [
            "soap", "shampoo", "toothpaste", "toothbrush", "facewash", "deodorant",
            "body wash", "hair oil", "body lotion", "razor", "sanitary pad", "sunscreen",
            "handwash", "face cream", "lip balm", "perfume",
        ],
        "cleaning": [
            "detergent", "dishwash", "floor cleaner", "toilet cleaner", "harpic",
            "vim", "surf excel", "colin", "phenyl", "mop", "broom", "scrubber",
            "fabric softener", "bleach",
        ],
        "baby_health": [
            "diaper", "baby food", "cerelac", "protein powder", "vitamin", "health drink",
            "horlicks", "bournvita", "complan",
        ],
        "kitchen_home": [
            "tissue", "aluminium foil", "cling wrap", "garbage bag", "candle", "matchbox",
            "agarbatti", "air freshener", "battery", "light bulb",
        ],
        "frozen": [
            "frozen", "ice cream", "pizza", "burger", "samosa", "paratha", "momos",
            "french fries", "nuggets", "ready to eat",
        ],
        "dry_fruits": [
            "almonds", "cashew", "raisins", "walnut", "dates", "peanuts", "pistachio",
            "mixed dry fruits", "fig", "apricot",
        ],
        "sweet": [
            "indian sweets", "dessert", "halwa", "gulab jamun",
        ],
        "paan": [
            "paan", "supari", "mouth freshener", "mukhwas",
        ],
        "pet_care": [
            "dog food", "cat food", "pet food", "pet shampoo",
        ],
    }

    # Flat list of all search terms (union of all groups, deduplicated, order preserved)
    search_terms = list(dict.fromkeys(term for terms in SEARCH_TERMS_BY_CATEGORY.values() for term in terms))

    def __init__(self, pincode: str, max_products: int = 10000, progress_callback=None,
                 selected_categories: list[str] | None = None):
        self.pincode = pincode
        self.max_products = max_products
        self.selected_categories = selected_categories
        self.products: list[Product] = []
        self._captured_responses: list[dict] = []
        self._processed_urls: set = set()
        self._seen_ids: set = set()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.lat, self.lng = get_coords(pincode)
        self._progress_callback = progress_callback

    def _get_filtered_category_paths(self) -> list[str]:
        """Return category paths filtered by selected_categories. Returns all if none selected or 'all'."""
        if not self.CATEGORY_MAP:
            return []
        if not self.selected_categories or "all" in self.selected_categories:
            return [path for paths in self.CATEGORY_MAP.values() for path in paths]
        result = []
        for cat_name in self.selected_categories:
            result.extend(self.CATEGORY_MAP.get(cat_name, []))
        return result

    def _get_filtered_search_terms(self) -> list[str]:
        """Return search terms filtered by selected_categories. Returns all if none selected or 'all'."""
        if not self.selected_categories or "all" in self.selected_categories:
            return self.search_terms
        groups = set()
        for cat_name in self.selected_categories:
            groups.update(self.CATEGORY_SEARCH_MAP.get(cat_name, []))
        if not groups:
            return self.search_terms
        terms = []
        for group in groups:
            terms.extend(self.SEARCH_TERMS_BY_CATEGORY.get(group, []))
        return terms

    async def init_browser(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=settings.HEADLESS,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self.context = await self.browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        self.page = await self.context.new_page()
        self.page.on("response", self._on_response)

    async def _on_response(self, response):
        try:
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct and response.status == 200:
                body = await response.text()
                if len(body) > 100 and any(kw in body.lower() for kw in ["product", "price", "mrp", "name", "selling", "inventory"]):
                    try:
                        data = json.loads(body)
                        self._captured_responses.append({"url": url, "data": data})
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass

    async def close(self):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _extract_products_from_json(self, data, depth=0) -> list[dict]:
        if depth > 8:
            return []
        products = []
        if isinstance(data, dict):
            has_name = any(k in data for k in ["name", "product_name", "title", "display_name", "productName"])
            has_price = any(k in data for k in ["price", "mrp", "selling_price", "offer_price", "sp", "sellingPrice", "finalPrice"])
            if has_name and has_price:
                products.append(data)
            for val in data.values():
                products.extend(self._extract_products_from_json(val, depth + 1))
        elif isinstance(data, list):
            for item in data:
                products.extend(self._extract_products_from_json(item, depth + 1))
        return products

    def _parse_generic_product(self, p: dict) -> Product | None:
        try:
            name = ""
            for key in ["name", "product_name", "title", "display_name", "productName", "product_title"]:
                val = p.get(key)
                if val and isinstance(val, str) and len(val) > 1:
                    name = val.strip()
                    break
            if not name:
                return None

            price = 0.0
            for key in ["price", "selling_price", "offer_price", "sp", "sellingPrice", "finalPrice", "salePrice", "sale_price"]:
                val = p.get(key)
                if val:
                    try:
                        price = float(str(val).replace("₹", "").replace(",", "").strip())
                        if price > 50000:
                            price /= 100
                        if price > 0:
                            break
                    except (ValueError, TypeError):
                        continue
            pricing = p.get("pricing", p.get("priceInfo", {}))
            # Also check if "price" key itself holds a nested dict (common in Blinkit API)
            if isinstance(p.get("price"), dict):
                pricing = p["price"]
            if isinstance(pricing, dict) and price == 0:
                for key in ["price", "selling_price", "finalPrice", "sp", "offer_price"]:
                    val = pricing.get(key)
                    if val:
                        try:
                            price = float(str(val).replace("₹", "").replace(",", "").strip())
                            if price > 50000:
                                price /= 100
                            if price > 0:
                                break
                        except (ValueError, TypeError):
                            continue

            mrp = None
            for key in ["mrp", "marked_price", "original_price", "maxPrice", "max_price", "markedPrice"]:
                val = p.get(key) or (pricing.get(key) if isinstance(pricing, dict) else None)
                if val:
                    try:
                        mrp = float(str(val).replace("₹", "").replace(",", "").strip())
                        if mrp > 50000:
                            mrp /= 100
                        if mrp > 0:
                            break
                    except (ValueError, TypeError):
                        continue

            brand = "Unknown"
            for key in ["brand", "brand_name", "brandName", "manufacturer"]:
                val = p.get(key)
                if val and isinstance(val, str) and len(val) > 0:
                    brand = val.strip()
                    break
            if brand == "Unknown" and name:
                brand = name.split()[0]

            unit = None
            for key in ["unit", "weight", "quantity", "pack_size", "packSize", "unitOfMeasure", "pack_desc", "variant"]:
                val = p.get(key)
                if val and str(val).strip():
                    unit = str(val).strip()
                    break

            category = None
            for key in ["category", "category_name", "categoryName", "l1_category", "l1Category", "type"]:
                val = p.get(key)
                if val and isinstance(val, str):
                    category = val.strip()
                    break

            in_stock = True
            for key in ["in_stock", "inStock", "available", "is_available", "inventory"]:
                val = p.get(key)
                if val is not None:
                    if isinstance(val, bool):
                        in_stock = val
                    elif isinstance(val, (int, float)):
                        in_stock = val > 0
                    elif isinstance(val, str):
                        in_stock = val.lower() not in ("false", "0", "no", "out")
                    break

            image = None
            for key in ["image_url", "image", "imageUrl", "thumbnail", "img_url"]:
                val = p.get(key)
                if val and isinstance(val, str) and val.startswith("http"):
                    image = val
                    break
            if not image:
                images = p.get("images", [])
                if isinstance(images, list) and images:
                    img = images[0]
                    if isinstance(img, str):
                        image = img
                    elif isinstance(img, dict):
                        image = img.get("url") or img.get("src")

            return Product(
                product_name=name, brand=brand, price=price, mrp=mrp, unit=unit,
                category=category, sub_category=None, platform=self.platform_name,
                pincode=self.pincode, in_stock=in_stock, scraped_at=self.now_iso(), image_url=image,
            )
        except Exception:
            return None

    async def _extract_from_page_html(self):
        try:
            html = await self.page.content()
            next_data_match = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if next_data_match:
                try:
                    data = json.loads(next_data_match.group(1))
                    return self._extract_products_from_json(data)
                except json.JSONDecodeError:
                    pass
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            products = []
            for sc in script_matches:
                if len(sc) < 200 or len(sc) > 500000:
                    continue
                if not any(kw in sc.lower() for kw in ['"product', '"price"', '"mrp"']):
                    continue
                for match in re.finditer(r'(\{[^{}]{50,}\}|\[[^\[\]]{50,}\])', sc):
                    try:
                        data = json.loads(match.group())
                        products.extend(self._extract_products_from_json(data))
                    except (json.JSONDecodeError, RecursionError):
                        continue
            return products
        except Exception:
            return []

    async def _wait_for_network_settle(self, min_wait=0.3, max_wait=1.5, settle_window=0.3):
        """Wait until no new API responses arrive within settle_window, bounded by min/max."""
        await asyncio.sleep(min_wait)
        elapsed = min_wait
        while elapsed < max_wait:
            prev_count = len(self._captured_responses)
            await asyncio.sleep(settle_window)
            elapsed += settle_window
            if len(self._captured_responses) == prev_count:
                break

    async def _report_progress(self):
        """Report progress via callback if set."""
        if self._progress_callback:
            await self._progress_callback(self.platform_name, self.pincode, len(self.products))

    async def _scroll_page(self, times=5, delay=0.7):
        """Scroll down to trigger lazy loading."""
        idle_count = 0
        for _ in range(times):
            prev = len(self._captured_responses)
            current_height = await self.page.evaluate("document.body.scrollHeight")
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(delay)
            new_height = await self.page.evaluate("document.body.scrollHeight")
            if len(self._captured_responses) == prev and new_height == current_height:
                idle_count += 1
                if idle_count >= 2:
                    break
            else:
                idle_count = 0

    def _process_responses(self) -> int:
        """Process captured API responses, return count of new products."""
        count = 0
        for resp in self._captured_responses:
            url = resp["url"]
            if url in self._processed_urls:
                continue
            self._processed_urls.add(url)
            raw = self._extract_products_from_json(resp["data"])
            for rp in raw:
                pid = str(rp.get("id") or rp.get("product_id") or rp.get("productId") or rp.get("slug") or rp.get("name", ""))
                if pid in self._seen_ids:
                    continue
                self._seen_ids.add(pid)
                product = self._parse_generic_product(rp)
                if product:
                    self.products.append(product)
                    count += 1
        return count

    async def _visit_and_collect(self, url, scroll_times=5):
        """Visit a URL, scroll, and collect products from API responses."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._wait_for_network_settle(0.5, 3.0)
            await self._scroll_page(times=scroll_times, delay=0.8)
            count = self._process_responses()
            await self._report_progress()
            return count
        except Exception as e:
            print(f"[{self.platform_name}] Visit {url} error: {e}")
            return 0

    async def _search_and_capture(self, search_url_fn):
        """Search with filtered terms and collect products. Exits early after 10 consecutive empty searches."""
        consecutive_empty = 0
        max_consecutive_empty = 10
        for term in self._get_filtered_search_terms():
            if len(self.products) >= self.max_products:
                break
            if consecutive_empty >= max_consecutive_empty:
                print(f"[{self.platform_name}] Early exit: {max_consecutive_empty} consecutive searches yielded 0 new products. "
                      f"Total so far: {len(self.products)}. Likely location not set or site blocking.")
                break
            try:
                before = len(self.products)
                url = search_url_fn(term)
                await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await self._wait_for_network_settle(0.5, 3.0)
                await self._scroll_page(times=5, delay=0.8)
                new = self._process_responses()
                await self._report_progress()

                # Fallback: HTML embedded JSON
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

                after = len(self.products)
                if after > before:
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
            except Exception as e:
                print(f"[{self.platform_name}] Search '{term}' error: {e}")
                consecutive_empty += 1
                continue

    async def _visit_categories_with_early_exit(self, categories, scroll_times=6, max_consecutive_empty=5):
        """Browse categories and collect products. Exits early after consecutive empty categories."""
        consecutive_empty = 0
        for cat in categories:
            if len(self.products) >= self.max_products:
                break
            if consecutive_empty >= max_consecutive_empty:
                print(f"[{self.platform_name}] Early exit from categories: {max_consecutive_empty} consecutive categories yielded 0 new products. "
                      f"Total so far: {len(self.products)}.")
                break
            url = cat if cat.startswith('http') else f"{self.base_url}{cat}"
            new = await self._visit_and_collect(url, scroll_times=scroll_times)
            if new > 0:
                consecutive_empty = 0
                print(f"[{self.platform_name}] Category: +{new} (total: {len(self.products)})")
            else:
                consecutive_empty += 1

    @abstractmethod
    async def scrape_all(self) -> list[Product]:
        ...
