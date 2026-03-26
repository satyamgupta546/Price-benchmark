import csv
import io
from datetime import datetime

from app.models.product import Product

PLATFORM_NAMES = {
    "blinkit": "Blinkit",
    "zepto": "Zepto",
    "instamart": "Swiggy Instamart",
    "jiomart": "JioMart",
    "flipkart_minutes": "Flipkart Minutes",
}


def generate_csv(products: list[Product], pincode: str) -> tuple[str, str]:
    """Generate comparison-format CSV: one row per product, platform prices as columns."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"PriceBenchmark_{pincode}_{date_str}.csv"

    # Find active platforms
    active_platforms = sorted(set(p.platform for p in products))

    # Group by normalized product name
    product_map: dict[str, dict] = {}
    for p in products:
        key = (p.product_name or "").lower().strip()
        if not key:
            continue
        if key not in product_map:
            product_map[key] = {
                "product_name": p.product_name,
                "brand": p.brand or "",
                "unit": p.unit or "",
                "category": p.category or "",
                "pincode": p.pincode or "",
                "prices": {},
            }
        if p.platform not in product_map[key]["prices"] or p.price > 0:
            product_map[key]["prices"][p.platform] = {
                "price": p.price,
                "mrp": p.mrp,
                "in_stock": p.in_stock,
            }

    rows = sorted(product_map.values(), key=lambda x: x["product_name"])

    output = io.StringIO()
    writer = csv.writer(output)

    # Headers
    headers = ["sr_no", "product_name", "brand", "unit", "category", "pincode"]
    for plat in active_platforms:
        name = PLATFORM_NAMES.get(plat, plat)
        headers.extend([f"{name}_price", f"{name}_mrp", f"{name}_stock"])
    headers.extend(["cheapest_platform", "cheapest_price", "price_diff"])
    writer.writerow(headers)

    # Data rows
    for idx, item in enumerate(rows, 1):
        row = [
            idx,
            item["product_name"],
            item["brand"],
            item["unit"],
            item["category"],
            item["pincode"],
        ]

        valid_prices = []
        for plat in active_platforms:
            info = item["prices"].get(plat)
            if info:
                row.append(f"{info['price']:.2f}" if info["price"] > 0 else "")
                row.append(f"{info['mrp']:.2f}" if info["mrp"] and info["mrp"] > 0 else "")
                row.append("Yes" if info["in_stock"] else "No")
                if info["price"] > 0:
                    valid_prices.append((PLATFORM_NAMES.get(plat, plat), info["price"]))
            else:
                row.extend(["", "", ""])

        if valid_prices:
            valid_prices.sort(key=lambda x: x[1])
            cheapest_name, cheapest_price = valid_prices[0]
            most_expensive = valid_prices[-1][1]
            row.append(cheapest_name)
            row.append(f"{cheapest_price:.2f}")
            row.append(f"{most_expensive - cheapest_price:.2f}" if len(valid_prices) > 1 else "0.00")
        else:
            row.extend(["", "", ""])

        writer.writerow(row)

    return output.getvalue(), filename
