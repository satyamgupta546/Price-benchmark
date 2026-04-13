"""
Stage 4: Image-based matching using perceptual hashing (pHash).

For each unmatched Anakin SKU (after Stage 1-3):
  1. Download Anakin's product image (from samaan-backend / Image_Link)
  2. Compute pHash
  3. Compare against pHash of every SAM BFS pool product image
  4. Best visual match above threshold → new mapping

Skips loose items (name contains "loose").

Usage:
    python3 scripts/stage4_image_match.py 834002 [blinkit|jiomart]
"""
import asyncio
import io
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image
import imagehash

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# pHash similarity threshold (0 = identical, lower = more similar)
# pHash returns a hash of 64 bits; hamming distance ≤ 10 is strong match
PHASH_THRESHOLD = 12


def download_image(url: str, timeout: int = 10) -> Image.Image | None:
    """Download image from URL, return PIL Image or None."""
    if not url or not url.startswith("http"):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


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

    if not ana_path or not sam_path:
        print(f"[img] ERROR: missing files for {platform} {pincode}", file=sys.stderr)
        sys.exit(1)

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
    print()

    # Step 1: Pre-compute pHash for SAM BFS pool images
    print("[img] Computing pHash for SAM pool images...", flush=True)
    sam_hashes: list[tuple[dict, imagehash.ImageHash]] = []
    pool = sam["products"]
    for i, p in enumerate(pool):
        img_url = p.get("image_url")
        if not img_url:
            continue
        img = download_image(img_url)
        if img:
            h = compute_phash(img)
            sam_hashes.append((p, h))
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(pool)}] {len(sam_hashes)} hashed", flush=True)

    print(f"[img] SAM pool: {len(sam_hashes)} images hashed out of {len(pool)}")
    print()

    if not sam_hashes:
        print("[img] No SAM images to compare against. Aborting.", flush=True)
        return

    # Step 2: For each unmatched Anakin SKU, find best image match
    print("[img] Matching unmatched products by image...", flush=True)
    new_matches = []
    no_image = 0
    no_match = 0

    for i, sku in enumerate(unmatched):
        ana_img_url = clean_str(sku.get("Image_Link"))
        if not ana_img_url or not ana_img_url.startswith("http"):
            no_image += 1
            continue

        ana_img = download_image(ana_img_url)
        if not ana_img:
            no_image += 1
            continue

        ana_hash = compute_phash(ana_img)

        # Find best match in SAM pool
        best_dist = 999
        best_match = None
        for sam_p, sam_h in sam_hashes:
            dist = ana_hash - sam_h  # hamming distance
            if dist < best_dist:
                best_dist = dist
                best_match = sam_p

        if best_match and best_dist <= PHASH_THRESHOLD:
            new_matches.append({
                "item_code": sku.get("Item_Code"),
                "anakin_name": sku.get("Item_Name"),
                "anakin_brand": sku.get("Brand"),
                "anakin_image": ana_img_url,
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
            print(f"  [{i+1}/{len(unmatched)}] {len(new_matches)} matched, {no_image} no-img, {no_match} no-match", flush=True)

    print()
    print("=" * 60)
    print(f"STAGE 4 RESULT — Image matching ({platform}, {pincode})")
    print("=" * 60)
    print(f"Input (unmatched):    {len(unmatched)}")
    print(f"New image matches:    {len(new_matches)}")
    print(f"No Anakin image:      {no_image}")
    print(f"No match (dist>{PHASH_THRESHOLD}): {no_match}")
    print()

    if new_matches:
        print("Sample matches (top 5 by distance):")
        for m in sorted(new_matches, key=lambda x: x["phash_distance"])[:5]:
            print(f"  [dist={m['phash_distance']}] {m['anakin_name'][:45]}")
            print(f"          → {m['sam_product_name'][:45]}")

    # Save
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_image_match_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "platform": platform,
            "compared_at": datetime.now().isoformat(),
            "metrics": {
                "input": len(unmatched),
                "new_matches": len(new_matches),
                "no_image": no_image,
                "no_match": no_match,
            },
            "new_mappings": new_matches,
        }, f, indent=2, default=str)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
