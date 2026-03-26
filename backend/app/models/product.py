from pydantic import BaseModel


class Product(BaseModel):
    product_name: str
    brand: str
    price: float
    mrp: float | None = None
    unit: str | None = None
    category: str | None = None
    sub_category: str | None = None
    platform: str
    pincode: str
    in_stock: bool = True
    scraped_at: str
    image_url: str | None = None


class PlatformResult(BaseModel):
    platform: str
    pincode: str
    status: str  # "success" | "partial" | "failed"
    total_products: int
    scrape_duration_seconds: float
    products: list[Product]
    error_message: str | None = None


class ScrapeRequest(BaseModel):
    pincodes: list[str]
    platforms: list[str]
    categories: dict[str, list[str]] = {}  # {platform: [category_names]} — empty means all
    max_products_per_platform: int = 500


class ScrapeResponse(BaseModel):
    pincodes: list[str]
    results: list[PlatformResult]
    total_products: int
    total_duration_seconds: float
