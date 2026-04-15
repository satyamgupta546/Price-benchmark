"""
SAM Price Benchmark — Complete Dashboard (Streamlit)
Everything in ONE app — no FastAPI needed.

Run: streamlit run streamlit_app.py
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent
DATA = PROJECT_ROOT / "data"
VENV_PYTHON = str(PROJECT_ROOT / "backend" / "venv" / "bin" / "python")
SCRIPTS = PROJECT_ROOT / "scripts"

CITIES = {"834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur", "825301": "Hazaribagh"}
PLATFORM_SP = {"blinkit": "Blinkit_Selling_Price", "jiomart": "Jiomart_Selling_Price"}

st.set_page_config(page_title="SAM Dashboard", page_icon="🚀", layout="wide", initial_sidebar_state="expanded")

# Pipeline state (session)
if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False
if "pipeline_log" not in st.session_state:
    st.session_state.pipeline_log = []


# ── Helpers ──────────────────────────────────────────────

def clean(v):
    if v is None or str(v).strip().lower() in ("", "na", "nan", "null", "none"):
        return None
    return str(v).strip()


def load_anakin(platform, pincode):
    files = sorted(DATA.glob(f"anakin/{platform}_{pincode}_*.json"))
    if not files:
        return []
    return json.load(open(files[-1])).get("records", [])


def load_sam_prices(platform, pincode):
    files = sorted(DATA.glob(f"sam/{platform}_pdp_{pincode}_*.json"))
    files = [f for f in files if "partial" not in f.name]
    if not files:
        return {}
    d = json.load(open(files[-1]))
    prices = {}
    for p in d.get("products", []):
        ic = p.get("item_code")
        if ic and p.get("status") == "ok":
            prices[ic] = {
                "sam_sp": p.get("sam_selling_price") or p.get("hmlg_selling_price"),
                "sam_mrp": p.get("sam_mrp") or p.get("hmlg_mrp"),
                "sam_stock": "available" if (p.get("sam_in_stock") or p.get("hmlg_in_stock")) else "out_of_stock",
            }
    return prices


def get_coverage(pincode, platform):
    records = load_anakin(platform, pincode)
    sp_field = PLATFORM_SP.get(platform, "Blinkit_Selling_Price")
    usable = [r for r in records
              if clean(r.get(sp_field)) and "loose" not in (r.get("Item_Name") or "").lower()]
    sam = load_sam_prices(platform, pincode)
    matched = sum(1 for r in usable if r.get("Item_Code") in sam)
    return len(usable), matched


def build_comparison_df(pincode, platform):
    records = load_anakin(platform, pincode)
    sam = load_sam_prices(platform, pincode)
    sp_field = PLATFORM_SP.get(platform, "Blinkit_Selling_Price")
    stock_field = f"{'Blinkit' if platform == 'blinkit' else 'Jiomart'}_In_Stock_Remark"

    rows = []
    for r in records:
        ic = r.get("Item_Code")
        ana_sp_raw = clean(r.get(sp_field))
        if not ana_sp_raw:
            continue
        if "loose" in (r.get("Item_Name") or "").lower():
            continue
        try:
            ana_sp = float(ana_sp_raw)
        except ValueError:
            continue

        s = sam.get(ic, {})
        sam_sp = s.get("sam_sp")
        diff = round(sam_sp - ana_sp, 2) if (sam_sp and ana_sp) else None
        diff_pct = round(abs(diff) / ana_sp * 100, 1) if diff is not None else None

        rows.append({
            "Item Code": ic,
            "Product": r.get("Item_Name", ""),
            "Brand": r.get("Brand", ""),
            "Anakin SP": ana_sp,
            "Anakin Stock": clean(r.get(stock_field)) or "",
            "SAM SP": sam_sp,
            "SAM Stock": s.get("sam_stock", ""),
            "Diff ₹": diff,
            "Diff %": diff_pct,
            "Match": "✅" if (diff_pct is not None and diff_pct <= 5) else ("🟡" if diff_pct is not None and diff_pct <= 10 else ("❌" if diff_pct is not None else "—")),
        })
    return pd.DataFrame(rows)


def run_script(name, args=[], use_venv=False):
    python = VENV_PYTHON if use_venv else sys.executable
    env = os.environ.copy()
    env["METABASE_API_KEY"] = os.environ.get("METABASE_API_KEY", "")
    subprocess.run([python, str(SCRIPTS / name)] + args,
                   cwd=str(PROJECT_ROOT), env=env, capture_output=True)


def pipeline_thread(cities, platforms):
    """Run full pipeline in background thread."""
    st.session_state.pipeline_running = True
    st.session_state.pipeline_log = []
    env = os.environ.copy()
    env["METABASE_API_KEY"] = os.environ.get("METABASE_API_KEY", "")

    def log(msg):
        st.session_state.pipeline_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    try:
        for pin in cities:
            city = CITIES.get(pin, pin)

            log(f"📥 {city}: Fetching Anakin...")
            run_script("fetch_anakin_blinkit.py", [pin])
            run_script("fetch_anakin_jiomart.py", [pin])

            for plat in platforms:
                if pin == "825301" and plat == "jiomart":
                    log(f"⏭️ {city} Jiomart: skipped")
                    continue

                log(f"🔍 {city} {plat}: Stage 1 PDP...")
                if plat == "blinkit":
                    subprocess.run([VENV_PYTHON, str(SCRIPTS / "scrape_blinkit_pdps.py"), pin, "2"],
                                   cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)
                    partial = DATA / "sam" / f"blinkit_pdp_{pin}_latest_partial.json"
                    if partial.exists(): partial.unlink()
                    run_script("compare_pdp.py", [pin])
                elif plat == "jiomart":
                    subprocess.run([VENV_PYTHON, str(SCRIPTS / "scrape_jiomart_pdps.py"), pin, "2"],
                                   cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)
                    partial = DATA / "sam" / f"jiomart_pdp_{pin}_latest_partial.json"
                    if partial.exists(): partial.unlink()
                    run_script("compare_pdp_jiomart.py", [pin])

                log(f"🔗 {city} {plat}: Stage 2-3 cascade...")
                run_script("cascade_match.py", [pin, plat])
                run_script("stage3_match.py", [pin, plat])

                if plat == "jiomart":
                    log(f"🔎 {city} Jiomart: Stage 4 search...")
                    subprocess.run([VENV_PYTHON, str(SCRIPTS / "jiomart_search_match.py"), pin],
                                   cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)

                run_script("stage4_image_match.py", [pin, plat])
                run_script("stage5_barcode_match.py", [pin, plat])
                log(f"✅ {city} {plat}: Done!")

        log(f"📊 Generating reports...")
        subprocess.run([VENV_PYTHON, str(SCRIPTS / "daily_report.py"), "all", "--no-scrape"],
                       cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)
        log("🎉 Pipeline complete!")
    except Exception as e:
        log(f"❌ Error: {e}")
    finally:
        st.session_state.pipeline_running = False


# ── Sidebar ──────────────────────────────────────────────

with st.sidebar:
    st.title("🚀 SAM")
    st.caption("Price Benchmark Tool")
    st.caption("Replacing Anakin • ₹3L/month savings")
    st.divider()

    page = st.radio("Navigate", ["📊 Dashboard", "⚙️ Pipeline", "📋 Compare", "📥 Downloads"], label_visibility="collapsed")

    st.divider()
    st.caption(f"🕐 {datetime.now().strftime('%d %b %Y, %H:%M IST')}")

    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════
# PAGE 1: DASHBOARD
# ══════════════════════════════════════════════════════════

if page == "📊 Dashboard":
    st.title("📊 Coverage Dashboard")

    grand_usable = 0
    grand_matched = 0
    city_data = {}

    for pin, city in CITIES.items():
        city_data[pin] = {}
        for plat in ["blinkit", "jiomart"]:
            if pin == "825301" and plat == "jiomart":
                continue
            usable, matched = get_coverage(pin, plat)
            city_data[pin][plat] = {"usable": usable, "matched": matched}
            grand_usable += usable
            grand_matched += matched

    grand_pct = round(grand_matched * 100 / grand_usable, 1) if grand_usable else 0
    emoji = "🔥" if grand_pct >= 90 else ("⚡" if grand_pct >= 70 else "🔧")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.metric("Total Coverage", f"{grand_pct}% {emoji}", f"{grand_matched:,} / {grand_usable:,} products")
    with col2:
        st.metric("Cities", len(CITIES))
    with col3:
        st.metric("Platforms", "2 (Blinkit + Jiomart)")

    st.progress(min(grand_pct / 100, 1.0))
    st.divider()

    for pin, city in CITIES.items():
        st.subheader(f"🏙️ {city} ({pin})")
        cols = st.columns(2)
        for i, plat in enumerate(["blinkit", "jiomart"]):
            with cols[i]:
                if pin == "825301" and plat == "jiomart":
                    st.caption("Jiomart — N/A")
                    continue
                d = city_data.get(pin, {}).get(plat, {})
                usable = d.get("usable", 0)
                matched = d.get("matched", 0)
                pct = round(matched * 100 / usable, 1) if usable else 0
                color = "🟢" if pct >= 90 else ("🟡" if pct >= 70 else "🔴")
                st.metric(f"{color} {plat.capitalize()}", f"{pct}%", f"{matched} / {usable}")
                st.progress(min(pct / 100, 1.0))
        st.divider()


# ══════════════════════════════════════════════════════════
# PAGE 2: PIPELINE
# ══════════════════════════════════════════════════════════

elif page == "⚙️ Pipeline":
    st.title("⚙️ Pipeline Controls")
    st.caption("Select → Run → All 7 stages automatic")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🏙️ Cities")
        sel_cities = [pin for pin, city in CITIES.items()
                      if st.checkbox(f"{city} ({pin})", value=True, key=f"c_{pin}")]
    with col2:
        st.subheader("📦 Platforms")
        sel_platforms = []
        if st.checkbox("Blinkit", value=True, key="p_b"): sel_platforms.append("blinkit")
        if st.checkbox("Jiomart", value=True, key="p_j"): sel_platforms.append("jiomart")

    st.divider()

    if st.button("🚀 Run Pipeline Now", type="primary", use_container_width=True,
                  disabled=st.session_state.pipeline_running or not sel_cities or not sel_platforms):
        thread = threading.Thread(target=pipeline_thread, args=(sel_cities, sel_platforms))
        thread.start()
        st.success("Pipeline started!")

    if st.session_state.pipeline_running:
        st.info("🔄 Pipeline RUNNING...")
        st.progress(0.5)

    if st.session_state.pipeline_log:
        st.subheader("📜 Progress Log")
        log_container = st.container(height=400)
        with log_container:
            for entry in st.session_state.pipeline_log:
                if "❌" in entry:
                    st.error(entry)
                elif "✅" in entry or "🎉" in entry:
                    st.success(entry)
                else:
                    st.text(entry)

    if st.session_state.pipeline_running:
        time.sleep(3)
        st.rerun()


# ══════════════════════════════════════════════════════════
# PAGE 3: COMPARE
# ══════════════════════════════════════════════════════════

elif page == "📋 Compare":
    st.title("📋 Anakin vs SAM")

    col1, col2 = st.columns(2)
    with col1:
        sel_city = st.selectbox("City", list(CITIES.keys()), format_func=lambda x: f"{CITIES[x]} ({x})")
    with col2:
        sel_plat = st.selectbox("Platform", ["blinkit", "jiomart"])

    df = build_comparison_df(sel_city, sel_plat)

    if df.empty:
        st.warning(f"No data for {CITIES[sel_city]} {sel_plat}. Run pipeline first.")
    else:
        total = len(df)
        with_sam = df["SAM SP"].notna().sum()
        price_compared = df["Diff %"].notna().sum()
        within_5 = (df["Diff %"].dropna() <= 5).sum() if price_compared else 0
        pct_5 = round(within_5 * 100 / price_compared, 1) if price_compared else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Products", f"{total:,}")
        c2.metric("SAM Priced", f"{with_sam:,} ({with_sam * 100 // max(total, 1)}%)")
        c3.metric("Compared", f"{price_compared:,}")
        c4.metric("±5% Match", f"{pct_5}%" if price_compared else "—")

        st.divider()

        search = st.text_input("🔍 Search", placeholder="Product or brand...")
        if search:
            df = df[df["Product"].str.contains(search, case=False, na=False) |
                    df["Brand"].str.contains(search, case=False, na=False)]

        f1, f2 = st.columns(2)
        with f1:
            match_filter = st.multiselect("Match", ["✅", "🟡", "❌", "—"], default=["✅", "🟡", "❌", "—"])
        with f2:
            brand_filter = st.multiselect("Brand", sorted(df["Brand"].dropna().unique().tolist())[:30])

        if match_filter: df = df[df["Match"].isin(match_filter)]
        if brand_filter: df = df[df["Brand"].isin(brand_filter)]

        st.dataframe(
            df.sort_values("Diff %", ascending=False, na_position="last"),
            use_container_width=True, height=500,
            column_config={
                "Anakin SP": st.column_config.NumberColumn(format="₹%.0f"),
                "SAM SP": st.column_config.NumberColumn(format="₹%.0f"),
                "Diff ₹": st.column_config.NumberColumn(format="₹%.1f"),
                "Diff %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

        if df["Diff %"].notna().any():
            st.subheader("📈 Price Diff Distribution")
            diff_data = df["Diff %"].dropna()
            bins = {"Exact": 0, "0-2%": 0, "2-5%": 0, "5-10%": 0, "10-20%": 0, "20%+": 0}
            for d in diff_data:
                if d == 0: bins["Exact"] += 1
                elif d <= 2: bins["0-2%"] += 1
                elif d <= 5: bins["2-5%"] += 1
                elif d <= 10: bins["5-10%"] += 1
                elif d <= 20: bins["10-20%"] += 1
                else: bins["20%+"] += 1
            st.bar_chart(pd.Series(bins))

        st.download_button("📥 Download CSV", df.to_csv(index=False),
                           f"SAM_{CITIES[sel_city]}_{sel_plat}_{datetime.now().strftime('%Y%m%d')}.csv",
                           "text/csv", use_container_width=True)


# ══════════════════════════════════════════════════════════
# PAGE 4: DOWNLOADS
# ══════════════════════════════════════════════════════════

elif page == "📥 Downloads":
    st.title("📥 Download Reports")

    st.subheader("Excel (Anakin + SAM + Diff)")
    for pin, city in CITIES.items():
        files = sorted((DATA / "sam_output").glob(f"SAM_{city}_{pin}_*.xlsx"))
        if files:
            latest = files[-1]
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1: st.text(f"📄 {latest.name}")
            with c2: st.caption(f"{latest.stat().st_size // 1024} KB")
            with c3:
                with open(latest, "rb") as f:
                    st.download_button(f"⬇️ {city}", f.read(), latest.name, key=f"xl_{pin}")
        else:
            st.caption(f"⚠️ {city} — no Excel (run pipeline)")

    st.divider()
    st.subheader("CSV (Anakin format — 47 columns)")
    for pin, city in CITIES.items():
        files = sorted((DATA / "sam_output").glob(f"sam_competitor_prices_{pin}_*.csv"))
        if files:
            latest = files[-1]
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1: st.text(f"📄 {latest.name}")
            with c2: st.caption(f"{latest.stat().st_size // 1024} KB")
            with c3:
                with open(latest, "rb") as f:
                    st.download_button(f"⬇️ {city}", f.read(), latest.name, "text/csv", key=f"csv_{pin}")

st.divider()
st.caption("SAM v1.0 — Apna Mart's price benchmark. Replacing Anakin (₹3L/month savings).")
