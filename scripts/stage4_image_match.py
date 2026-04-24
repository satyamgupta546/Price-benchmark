"""
Stage 4: Image-based matching using perceptual hashing (pHash).

For each unmatched Anakin SKU (after Stage 1-3):
  1. Download Anakin's product image (from samaan-backend / Image_Link)
  2. Compute pHash
  3. Compare against pHash of every SAM BFS pool product image
  4. Best visual match above threshold -> new mapping

Fallbacks:
  - If Anakin Image_Link uses storage.cloud.google.com, auto-convert to
    storage.googleapis.com (public URL).
  - If Anakin image download fails after retry, try matching using the
    Blinkit PDP image from Anakin data (Blinkit_Product_Url) if available.
  - Retry image downloads once with a longer timeout.

Skips loose items (name contains "loose").

Usage:
    python3 scripts/stage4_image_match.py 834002 [blinkit|jiomart]
"""
import io
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from PIL import Image
import imagehash

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# pHash similarity threshold (0 = identical, lower = more similar)
# pHash returns a hash of 64 bits; hamming distance <= 10 is strong match
PHASH_THRESHOLD = 12


def fix_gcs_url(url: str) -> str:
    """Convert Google Cloud Storage console URLs to public API URLs.

    storage.cloud.google.com/bucket/path redirects to Google login (302).
    storage.googleapis.com/bucket/path serves the file directly (if public).
    """
    if not url:
        return url
    if "storage.cloud.google.com/" in url:
        return url.replace("storage.cloud.google.com/", "storage.googleapis.com/")
    return url


def download_image(url: str, timeout: int = 10, retries: int = 1) -> tuple[Image.Image | None, str]:
    """Download image from URL, return (PIL Image or None, error_reason).

    Retries once with a longer timeout on failure.
    Returns a reason string if download fails (for logging).
    """
    if not url or not url.startswith("http"):
        return None, "invalid_url"

    url = fix_gcs_url(url)

    for attempt in range(1 + retries):
        current_timeout = timeout if attempt == 0 else timeout * 2
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
            })
            with urllib.request.urlopen(req, timeout=current_timeout) as r:
                # Check content type to avoid downloading HTML login pages
                ct = r.headers.get("Content-Type", "")
                if "html" in ct.lower():
                    return None, f"html_response (ct={ct}, url may require auth)"

                data = r.read()
                if len(data) < 100:
                    return None, f"tiny_response ({len(data)} bytes)"

                img = Image.open(io.BytesIO(data)).convert("RGB")
                return img, ""

        except urllib.error.HTTPError as e:
            reason = f"http_{e.code}"
            if attempt < retries:
                continue
            return None, reason

        except urllib.error.URLError as e:
            reason = f"url_error ({e.reason})"
            if attempt < retries:
                continue
            return None, reason

        except Exception as e:
            reason = f"exception ({type(e).__name__}: {e})"
            if attempt < retries:
                continue
            return None, reason

    return None, "max_retries"


def compute_phash(img: Image.Image) -> imagehash.ImageHash:
    """Compute perceptual hash of an image."""
    return imagehash.phash(img, hash_size=8)


def latest_file(subdir: str, pattern: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


def clean_str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


def main(pincode: str, platform: str = "blinkit"):
    PLATFORM_FIELDS = {
        "blinkit": {"product_id": "Blinkit_Product_Id", "selling_price": "Blinkit_Selling_Price"},
        "jiomart": {"product_id": "Jiomart_Product_Id", "selling_price": "Jiomart_Selling_Price"},
    }
    pf = PLATFORM_FIELDS.get(platform, PLATFORM_FIELDS["blinkit"])

    ana_path = latest_file("anakin", f"{platform}_{pincode}_*.json")
    sam_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_{pincode}_*.json"), reverse=True):
        if "pdp" not in p.name:
            sam_path = p
            break

    if not ana_path:
        print(f"[img] No Anakin {platform} file for {pincode} — skipping", flush=True)
        sys.exit(0)
    if not sam_path:
        print(f"[img] No SAM {platform} BFS data for {pincode} — skipping", flush=True)
        sys.exit(0)

    print(f"[img] Platform: {platform}")
    print(f"[img] Anakin: {ana_path.name}")
    print(f"[img] SAM pool: {sam_path.name}")

    ana = json.load(open(ana_path))
    sam = json.load(open(sam_path))

    # Find unmatched non-loose usable SKUs
    usable_codes = {r.get("Item_Code") for r in ana["records"]
                    if r.get(pf["selling_price"]) not in (None, "", "NA", "nan")
                    and "loose" not in (r.get("Item_Name") or "").lower()}

    # Collect already-matched codes from Stage 1-3
    matched_codes: set[str] = set()
    for pattern in [f"{platform}_pdp_{pincode}_*_compare.json",
                    f"{platform}_cascade_{pincode}_*.json",
                    f"{platform}_stage3_{pincode}_*.json"]:
        for f in sorted((PROJECT_ROOT / "data" / "comparisons").glob(pattern)):
            d = json.load(open(f))
            for m in d.get("matches", []):
                if m.get("match_status") == "ok":
                    matched_codes.add(m.get("item_code"))
            for m in d.get("new_mappings", []):
                matched_codes.add(m.get("item_code"))

    unmatched = [r for r in ana["records"]
                 if r.get("Item_Code") in (usable_codes - matched_codes)]

    print(f"[img] Usable non-loose: {len(usable_codes)}")
    print(f"[img] Already matched: {len(matched_codes & usable_codes)}")
    print(f"[img] Unmatched (Stage 4 input): {len(unmatched)}")

    # Diagnose Anakin image availability
    ana_img_stats = {"has_url": 0, "empty": 0, "missing_field": 0}
    for sku in unmatched:
        raw = sku.get("Image_Link")
        url = clean_str(raw)
        if url and url.startswith("http"):
            ana_img_stats["has_url"] += 1
        elif "Image_Link" in sku:
            ana_img_stats["empty"] += 1
        else:
            ana_img_stats["missing_field"] += 1

    print(f"[img] Anakin images: {ana_img_stats['has_url']} have URL, "
          f"{ana_img_stats['empty']} empty, {ana_img_stats['missing_field']} field missing")
    print()

    # Step 1: Pre-compute pHash for SAM BFS pool images
    print("[img] Computing pHash for SAM pool images...", flush=True)
    sam_hashes: list[tuple[dict, imagehash.ImageHash]] = []
    sam_download_errors: dict[str, int] = {}
    pool = sam["products"]
    for i, p in enumerate(pool):
        img_url = p.get("image_url")
        if not img_url:
            continue
        img, err = download_image(img_url)
        if img:
            h = compute_phash(img)
            sam_hashes.append((p, h))
        elif err:
            sam_download_errors[err] = sam_download_errors.get(err, 0) + 1
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(pool)}] {len(sam_hashes)} hashed", flush=True)

    print(f"[img] SAM pool: {len(sam_hashes)} images hashed out of {len(pool)}")
    if sam_download_errors:
        print(f"[img] SAM download errors: {dict(sam_download_errors)}")
    print()

    if not sam_hashes:
        print("[img] No SAM images to compare against. Aborting.", flush=True)
        # Still save a report with 0 matches
        _save_report(pincode, platform, len(unmatched), [], len(unmatched), 0,
                     {"sam_pool_empty": True})
        return

    # Step 2: For each unmatched Anakin SKU, find best image match
    print("[img] Matching unmatched products by image...", flush=True)
    new_matches = []
    no_image = 0
    no_match = 0
    download_fail_reasons: dict[str, int] = {}

    for i, sku in enumerate(unmatched):
        ana_img_url = clean_str(sku.get("Image_Link"))

        # Try to download Anakin image
        ana_img = None
        if ana_img_url and ana_img_url.startswith("http"):
            ana_img, err = download_image(ana_img_url)
            if not ana_img and err:
                download_fail_reasons[err] = download_fail_reasons.get(err, 0) + 1

        # Fallback: if Anakin image unavailable but we have a Blinkit product URL,
        # try to find the SAM product by product_id and use its image
        if not ana_img:
            ana_product_id = clean_str(sku.get(pf["product_id"]))
            if ana_product_id:
                # If Anakin already has a mapped product_id, we can look it up in SAM
                # to get its image and compare against other SAM products
                for sam_p, sam_h in sam_hashes:
                    if str(sam_p.get("product_id")) == ana_product_id:
                        # Found the SAM product - use its image as Anakin's proxy
                        sam_img_url = sam_p.get("image_url")
                        if sam_img_url:
                            ana_img, _ = download_image(sam_img_url)
                        break

        if not ana_img:
            no_image += 1
            continue

        ana_hash = compute_phash(ana_img)

        # Find best match in SAM pool
        best_dist = 999
        best_match = None
        for sam_p, sam_h in sam_hashes:
            # Skip self-match (same product_id)
            ana_pid = clean_str(sku.get(pf["product_id"]))
            if ana_pid and str(sam_p.get("product_id")) == ana_pid:
                continue
            dist = ana_hash - sam_h  # hamming distance
            if dist < best_dist:
                best_dist = dist
                best_match = sam_p

        if best_match and best_dist <= PHASH_THRESHOLD:
            new_matches.append({
                "item_code": sku.get("Item_Code"),
                "anakin_name": sku.get("Item_Name"),
                "anakin_brand": sku.get("Brand"),
                "anakin_image": ana_img_url or "(used SAM proxy)",
                "sam_product_name": best_match.get("product_name"),
                "sam_brand": best_match.get("brand"),
                "sam_price": best_match.get("price"),
                "sam_mrp": best_match.get("mrp"),
                "sam_image": best_match.get("image_url"),
                "sam_product_id": best_match.get("product_id"),
                "phash_distance": best_dist,
                "match_method": "image_phash",
            })
        else:
            no_match += 1

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(unmatched)}] {len(new_matches)} matched, "
                  f"{no_image} no-img, {no_match} no-match", flush=True)

    print()
    print("=" * 60)
    print(f"STAGE 4 RESULT -- Image matching ({platform}, {pincode})")
    print("=" * 60)
    print(f"Input (unmatched):    {len(unmatched)}")
    print(f"New image matches:    {len(new_matches)}")
    print(f"No Anakin image:      {no_image}")
    print(f"No match (dist>{PHASH_THRESHOLD}): {no_match}")
    if download_fail_reasons:
        print(f"\nAnakin image download failures:")
        for reason, count in sorted(download_fail_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
    print()

    if new_matches:
        print("Sample matches (top 5 by distance):")
        for m in sorted(new_matches, key=lambda x: x["phash_distance"])[:5]:
            print(f"  [dist={m['phash_distance']}] {m['anakin_name'][:45]}")
            print(f"          -> {m['sam_product_name'][:45]}")

    _save_report(pincode, platform, len(unmatched), new_matches, no_image, no_match,
                 {"download_fail_reasons": download_fail_reasons,
                  "anakin_image_stats": ana_img_stats,
                  "sam_pool_hashed": len(sam_hashes),
                  "sam_pool_total": len(pool)})


def _save_report(pincode, platform, input_count, new_matches, no_image, no_match, extras=None):
    """Save results to JSON file."""
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_image_match_{pincode}_{ts}.json"

    report = {
        "pincode": pincode,
        "platform": platform,
        "compared_at": datetime.now().isoformat(),
        "metrics": {
            "input": input_count,
            "new_matches": len(new_matches),
            "no_image": no_image,
            "no_match": no_match,
        },
        "new_mappings": new_matches,
    }
    if extras:
        report["diagnostics"] = extras

    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
