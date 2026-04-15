"""Unit tests for scrape_blinkit_pdps.py helper functions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scrape_blinkit_pdps import (
    _find_product_in_json,
    _find_name_in_payload,
    _extract_price_from_product_dict,
)


def test_find_product_pid_price_no_name():
    """product_id + price but no name => should still match (has product_id key)."""
    data = {"w": {"product_id": "123", "mrp": 100, "offer_price": 80}}
    result = _find_product_in_json(data, "123")
    assert result is not None, "Should find product with product_id + price even without name"
    assert result["product_id"] == "123"


def test_find_product_pid_price_and_name():
    """product_id + price + name => should match."""
    data = {"w": {"product_id": "123", "name": "Salt", "mrp": 100, "offer_price": 80}}
    result = _find_product_in_json(data, "123")
    assert result is not None
    assert result["name"] == "Salt"


def test_find_product_generic_id_no_product_fields():
    """Generic 'id' without product-like fields => should NOT match."""
    data = {"tracking": {"id": "123", "event": "pageview"}}
    result = _find_product_in_json(data, "123")
    assert result is None, "Should not match tracking metadata"


def test_find_name_same_level():
    """Name and product_id at same dict level."""
    data = {"product_id": "555", "name": "Maggi Noodles", "price": 14}
    name = _find_name_in_payload(data, "555")
    assert name == "Maggi Noodles"


def test_find_name_parent_child_list():
    """Name at parent dict, product_id in child list item."""
    data = {
        "name": "Tata Salt 1kg",
        "variants": [
            {"product_id": "123", "mrp": 100, "offer_price": 80},
            {"product_id": "999", "mrp": 50},
        ],
    }
    name = _find_name_in_payload(data, "123")
    assert name == "Tata Salt 1kg", f"Expected 'Tata Salt 1kg', got {name!r}"


def test_find_name_parent_child_dict():
    """Name at parent dict, product_id in child dict."""
    data = {
        "name": "Amul Butter 500g",
        "pricing": {"product_id": "456", "mrp": 200, "offer_price": 180},
    }
    name = _find_name_in_payload(data, "456")
    assert name == "Amul Butter 500g", f"Expected 'Amul Butter 500g', got {name!r}"


def test_find_name_no_match():
    """No dict has target_pid => should return None."""
    data = {"product_id": "999", "name": "Wrong Product"}
    name = _find_name_in_payload(data, "123")
    assert name is None


def test_find_name_tracking_id_no_name():
    """Dict with generic 'id' matching but no name field => None."""
    data = {"id": "123", "event": "click"}
    name = _find_name_in_payload(data, "123")
    assert name is None, "Should not return name from tracking dict"


def test_extract_price_basic():
    """Basic offer_price + mrp."""
    sp, mrp = _extract_price_from_product_dict({"offer_price": 80, "mrp": 100})
    assert sp == 80.0
    assert mrp == 100.0


def test_extract_price_mrp_fallback():
    """SP exists but no MRP => MRP should equal SP."""
    sp, mrp = _extract_price_from_product_dict({"offer_price": 50})
    assert sp == 50.0
    assert mrp == 50.0, f"MRP should fallback to SP, got {mrp}"


def test_extract_price_nested():
    """Price in nested 'price' dict."""
    sp, mrp = _extract_price_from_product_dict({"price": {"offer_price": 120, "mrp": 150}})
    assert sp == 120.0
    assert mrp == 150.0


def test_extract_price_paise():
    """Price > 50000 should be treated as paise and divided by 100."""
    sp, mrp = _extract_price_from_product_dict({"offer_price": 8000, "mrp": 100000})
    assert sp == 8000.0  # under 50000, kept as-is
    assert mrp == 1000.0  # over 50000, divided by 100


def test_extract_price_scalar_price():
    """Top-level 'price' as scalar when no offer_price."""
    sp, mrp = _extract_price_from_product_dict({"price": 75})
    assert sp == 75.0
    assert mrp == 75.0  # MRP fallback


def test_find_name_grandparent():
    """Name at grandparent with pid in grandchild via child dict."""
    data = {
        "section": {
            "product_name": "Lays Classic",
            "details": {"product_id": "777", "mrp": 20},
        }
    }
    name = _find_name_in_payload(data, "777")
    assert name == "Lays Classic", f"Expected 'Lays Classic', got {name!r}"


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed out of {passed + failed}")
    sys.exit(1 if failed else 0)
