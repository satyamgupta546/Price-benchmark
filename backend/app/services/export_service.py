import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.models.product import Product

PLATFORM_NAMES = {
    "blinkit": "Blinkit",
    "zepto": "Zepto",
    "instamart": "Swiggy Instamart",
    "jiomart": "JioMart",
    "flipkart_minutes": "Flipkart Minutes",
}

PLATFORM_COLORS = {
    "blinkit": "FFF8C723",
    "zepto": "FF8B22CF",
    "instamart": "FFFC8019",
    "jiomart": "FF0078AD",
    "flipkart_minutes": "FF2874F0",
}

HEADERS = ["Sr No", "Product Name", "Brand", "Category", "Pincode", "Price", "MRP"]

# Styles
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="FF333333", end_color="FF333333", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin", color="DDDDDD"),
    top=Side(style="thin", color="DDDDDD"),
    bottom=Side(style="thin", color="DDDDDD"),
)


def _write_sheet(ws, products: list[Product], sheet_color: str = None):
    """Write products to a worksheet. Each product is a separate row — no dedup."""
    if sheet_color:
        ws.sheet_properties.tabColor = sheet_color

    # Write headers
    for col_idx, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    # Sort by pincode, then product name
    sorted_products = sorted(products, key=lambda p: (p.pincode, p.product_name.lower()))

    # Write data rows
    for idx, p in enumerate(sorted_products, 1):
        row = idx + 1  # +1 for header
        values = [
            idx,
            p.product_name,
            p.brand or "",
            p.category or "",
            p.pincode,
            p.price,
            p.mrp if p.mrp else "",
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col_idx, value=val)
            cell.border = THIN_BORDER
            if col_idx in (6, 7) and isinstance(val, (int, float)):
                cell.number_format = '#,##0.00'
            if col_idx == 5:  # pincode
                cell.alignment = Alignment(horizontal="center")

    # Auto-fit column widths
    col_widths = [8, 50, 20, 20, 10, 12, 12]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # Freeze header row
    ws.freeze_panes = "A2"


def generate_excel(products: list[Product], pincodes: str) -> tuple[bytes, str]:
    """Generate Excel with sheets: All + one per platform. Every product row kept as-is."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"PriceBenchmark_{pincodes}_{date_str}.xlsx"

    wb = Workbook()

    # Sheet 1: All products
    ws_all = wb.active
    ws_all.title = "All"
    # Add platform column for All sheet
    all_headers = ["Sr No", "Product Name", "Brand", "Category", "Platform", "Pincode", "Price", "MRP"]

    # Write All sheet manually (has extra Platform column)
    ws_all.sheet_properties.tabColor = "FF4CAF50"
    for col_idx, header in enumerate(all_headers, 1):
        cell = ws_all.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    sorted_all = sorted(products, key=lambda p: (p.pincode, p.platform, p.product_name.lower()))
    for idx, p in enumerate(sorted_all, 1):
        row = idx + 1
        values = [
            idx,
            p.product_name,
            p.brand or "",
            p.category or "",
            PLATFORM_NAMES.get(p.platform, p.platform),
            p.pincode,
            p.price,
            p.mrp if p.mrp else "",
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws_all.cell(row=row, column=col_idx, value=val)
            cell.border = THIN_BORDER
            if col_idx in (7, 8) and isinstance(val, (int, float)):
                cell.number_format = '#,##0.00'
            if col_idx == 6:
                cell.alignment = Alignment(horizontal="center")

    all_widths = [8, 50, 20, 20, 18, 10, 12, 12]
    for i, width in enumerate(all_widths, 1):
        ws_all.column_dimensions[get_column_letter(i)].width = width
    ws_all.freeze_panes = "A2"

    # Per-platform sheets
    platforms_in_data = sorted(set(p.platform for p in products))
    for platform in platforms_in_data:
        platform_products = [p for p in products if p.platform == platform]
        if not platform_products:
            continue

        sheet_name = PLATFORM_NAMES.get(platform, platform)
        # Excel sheet names max 31 chars
        ws = wb.create_sheet(title=sheet_name[:31])
        color = PLATFORM_COLORS.get(platform, "FF666666").replace("FF", "", 1)
        _write_sheet(ws, platform_products, sheet_color=color)

    # Write to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return output.getvalue(), filename
