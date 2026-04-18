"""
DMart Ready Scraper — Pure API-based (no Playwright needed!).

DMart has an open JSON API at digital.dmart.in — no auth, no cookies.
This is the simplest and fastest scraper in the project.

API: GET https://digital.dmart.in/api/v3/plp/{slug}?page={n}&size=100&storeId={id}&channel=web&buryOOS=true

Available cities: Raipur (492001). NOT available in Ranchi, Kolkata, Hazaribagh.

Usage:
    from app.scrapers.dmart_scraper import DMartScraper
    scraper = DMartScraper(pincode="492001")
    products = await scraper.scrape_all()
"""
import json
import urllib.request
from datetime import datetime

from app.models.product import Product

# DMart storeId per pincode (discovered via browser session)
# Add new store IDs as DMart expands to more cities
DMART_STORE_IDS = {
    "492001": "10677",   # Raipur — needs verification, may need browser discovery
}

DMART_API_BASE = "https://digital.dmart.in/api/v3/plp"
DMART_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0"

# Grocery + FMCG categories only
GROCERY_CATEGORIES = [
    ("Grocery", "Dals", "dals-aesc-dals"),
    ("Grocery", "Pulses", "pulses-aesc-pulses3"),
    ("Grocery", "Dry Fruits", "dry-fruits-aesc-dryfruits2"),
    ("Grocery", "Cooking Oil", "cooking-oil-aesc-cookingoil"),
    ("Grocery", "Ghee & Vanaspati", "ghee---vanaspati-aesc-gheeandvanaspati"),
    ("Grocery", "Flours & Grains", "flours---grains-aesc-floursandgrains4"),
    ("Grocery", "Rice & Rice Products", "rice---rice-products-aesc-riceandriceproducts4"),
    ("Grocery", "Masala & Spices", "masala---spices-aesc-masalaandspices4"),
    ("Grocery", "Salt / Sugar / Jaggery", "salt---sugar---jaggery-aesc-saltsugarjaggery4"),
    ("Dairy & Beverages", "Beverages", "beverages-aesc-beverages"),
    ("Dairy & Beverages", "Dairy", "dairy-aesc-dairy"),
    ("Packaged Food", "Biscuits & Cookies", "biscuits---cookies-aesc-biscuitsandcookies"),
    ("Packaged Food", "Snacks & Farsans", "snacks---farsans-aesc-snacksandfarsans"),
    ("Packaged Food", "Breakfast Cereals", "breakfast-cereals-aesc-breakfastcereals"),
    ("Packaged Food", "Chocolates & Candies", "chocolates---candies"),
    ("Packaged Food", "Pasta & Noodles", "pasta---noodles-aesc-pastaandnoodles"),
    ("Packaged Food", "Ready to Cook", "ready-to-cook-aesc-readytocook"),
    ("Packaged Food", "Healthy Food", "health-food-aesc-healthfood"),
    ("Packaged Food", "Bakery", "bakery-aesc-bakery"),
    ("Packaged Food", "Frozen Food", "frozen-foods-aesc-frozenfoods"),
    ("Packaged Food", "Sweets", "sweets-aesc-sweets"),
    ("Fruits & Vegetables", "Fresh Fruits", "fresh-fruits-aesc-freshfruits"),
    ("Fruits & Vegetables", "Vegetables", "vegetables-aesc-vegetables"),
    ("Personal Care", "Bath & Body", "bath-body"),
    ("Personal Care", "Oral Care", "oral-care-aesc-oralcare"),
    ("Baby & Kids", "Baby Care", "baby-care-aesc-babycare"),
    ("Baby & Kids", "Baby Food", "baby-food-aesc-babyfood"),
    ("Baby & Kids", "Diapers & Wipes", "diapers---wipes-aesc-diapersandwipes"),
    ("Home & Cleaning", "Detergent & Fabric Care", "detergent---fabric-care-aesc-detergentsandfabriccare"),
    ("Home & Cleaning", "Cleaners", "cleaners-aesc-cleaners"),
    ("Home & Cleaning", "Utensil Cleaners", "utensil-cleaners-aesc-utensilcleaners"),
]


class DMartScraper:
    """Pure API scraper for DMart Ready — no browser needed."""

    def __init__(self, pincode: str, max_products: int = 10000):
        self.pincode = pincode
        self.max_products = max_products
        self.store_id = DMART_STORE_IDS.get(pincode, "10677")
        self.products: list[Product] = []
        self._seen_ids: set[str] = set()

    def _api_url(self, slug: str, page: int) -> str:
        return (f"{DMART_API_BASE}/{slug}?page={page}&buryOOS=true"
                f"&size=100&channel=web&storeId={self.store_id}")

    def _fetch_page(self, slug: str, page: int) -> dict:
        """Fetch one page from DMart PLP API."""
        url = self._api_url(slug, page)
        req = urllib.request.Request(url, headers={"User-Agent": DMART_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"[dmart] API error: {e}")
            return {}

    def _parse_product(self, item: dict, category: str, sub_category: str) -> Product | None:
        """Parse one product from DMart API response."""
        skus = item.get("sKUs", [])
        if not skus:
            return None

        # Use default variant (first SKU)
        sku = skus[0]
        name = sku.get("name") or item.get("name", "")
        if not name:
            return None

        pid = str(sku.get("skuUniqueID", ""))
        if pid in self._seen_ids:
            return None
        self._seen_ids.add(pid)

        mrp = sku.get("priceMRP")
        sp = sku.get("priceSALE") or mrp
        in_stock = str(sku.get("invStatus", "0")) == "2"
        unit = sku.get("variantTextValue", "")

        # Brand = manufacturer field on DMart
        brand = item.get("manufacturer", name.split()[0] if name else "")

        # Product URL
        seo_token = item.get("seo_token_ntk", "")
        product_url = f"https://www.dmart.in/product/{seo_token}?selectedProd={pid}" if seo_token else ""

        # Image
        image_url = None
        if item.get("imageURL"):
            image_url = item["imageURL"]
            if not image_url.startswith("http"):
                image_url = f"https://cdn.dmart.in{image_url}"

        # Barcode/EAN
        barcode = str(sku.get("articleNumber", ""))

        return Product(
            product_name=name,
            brand=brand,
            price=sp,
            mrp=mrp,
            unit=unit,
            category=category,
            sub_category=sub_category,
            platform="dmart",
            pincode=self.pincode,
            in_stock=in_stock,
            scraped_at=datetime.now().isoformat(),
            image_url=image_url,
            product_id=pid,
            product_url=product_url,
            barcode=barcode,
        )

    def _scrape_category(self, category: str, sub_category: str, slug: str) -> int:
        """Scrape all pages of one category."""
        page = 1
        total_new = 0
        while len(self.products) < self.max_products:
            data = self._fetch_page(slug, page)
            items = data.get("products", [])
            if not items:
                break

            for item in items:
                product = self._parse_product(item, category, sub_category)
                if product:
                    self.products.append(product)
                    total_new += 1

            total_records = data.get("totalRecords", 0)
            if page * 100 >= total_records:
                break
            page += 1
            if page > 50:  # safety cap
                break

        # Also process OOS products (useful for mapping)
        oos_items = data.get("oosProducts", []) if data else []
        for item in oos_items:
            product = self._parse_product(item, category, sub_category)
            if product:
                product.in_stock = False
                self.products.append(product)
                total_new += 1

        return total_new

    async def scrape_all(self) -> list[Product]:
        """Scrape all grocery categories. Returns list of products.
        Note: This is sync internally (API calls, no browser) but async interface
        for compatibility with other scrapers."""
        if self.pincode not in DMART_STORE_IDS:
            print(f"[dmart] DMart not available for pincode {self.pincode}")
            return []

        print(f"[dmart] Starting scrape for pincode {self.pincode} (storeId: {self.store_id})")

        for category, sub_category, slug in GROCERY_CATEGORIES:
            if len(self.products) >= self.max_products:
                break
            new = self._scrape_category(category, sub_category, slug)
            if new > 0:
                print(f"[dmart] {sub_category}: +{new} (total: {len(self.products)})")

        print(f"[dmart] Final: {len(self.products)} products for {self.pincode}")
        return self.products

    async def close(self):
        """No-op — no browser to close."""
        pass
