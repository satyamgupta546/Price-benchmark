"""Pipeline control API — run, schedule, and monitor SAM pipeline from frontend."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter(prefix="/api/pipeline")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VENV_PYTHON = str(PROJECT_ROOT / "backend" / "venv" / "bin" / "python")

# Pipeline state (in-memory)
_state = {
    "running": False,
    "progress": [],
    "started_at": None,
    "completed_at": None,
    "config": {"cities": [], "platforms": []},
    "schedule": {"enabled": False, "time": "10:30", "cities": ["834002", "712232", "492001", "825301"], "platforms": ["blinkit", "jiomart"]},
    "last_result": None,
}

CITIES = {"834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur", "825301": "Hazaribagh"}


class PipelineRequest(BaseModel):
    cities: list[str] = ["834002"]
    platforms: list[str] = ["blinkit"]


class ScheduleRequest(BaseModel):
    enabled: bool = False
    time: str = "10:30"
    cities: list[str] = ["834002", "712232", "492001", "825301"]
    platforms: list[str] = ["blinkit", "jiomart"]


def _log(msg: str):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg}
    _state["progress"].append(entry)
    print(f"[pipeline] {msg}", flush=True)


def _run_pipeline(cities: list[str], platforms: list[str]):
    """Run pipeline in background thread."""
    _state["running"] = True
    _state["progress"] = []
    _state["started_at"] = datetime.now().isoformat()
    _state["config"] = {"cities": cities, "platforms": platforms}

    env = os.environ.copy()
    env["METABASE_API_KEY"] = os.environ.get("METABASE_API_KEY", "")

    try:
        for pin in cities:
            city = CITIES.get(pin, pin)

            # Fetch Anakin
            _log(f"📥 {city}: Fetching Anakin data...")
            for script in ["fetch_anakin_blinkit.py", "fetch_anakin_jiomart.py"]:
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / script), pin],
                             cwd=str(PROJECT_ROOT), env=env, capture_output=True)

            for plat in platforms:
                if pin == "825301" and plat == "jiomart":
                    _log(f"⏭️ {city} Jiomart: skipped (no delivery)")
                    continue

                # Stage 1: PDP
                _log(f"🔍 {city} {plat}: Stage 1 PDP scrape...")
                if plat == "blinkit":
                    subprocess.run([VENV_PYTHON, str(PROJECT_ROOT / "scripts" / "scrape_blinkit_pdps.py"), pin, "2"],
                                 cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)
                    # Clean partial
                    partial = PROJECT_ROOT / "data" / "sam" / f"blinkit_pdp_{pin}_latest_partial.json"
                    if partial.exists():
                        partial.unlink()
                    subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "compare_pdp.py"), pin],
                                 cwd=str(PROJECT_ROOT), env=env, capture_output=True)
                elif plat == "jiomart":
                    subprocess.run([VENV_PYTHON, str(PROJECT_ROOT / "scripts" / "scrape_jiomart_pdps.py"), pin, "2"],
                                 cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)
                    partial = PROJECT_ROOT / "data" / "sam" / f"jiomart_pdp_{pin}_latest_partial.json"
                    if partial.exists():
                        partial.unlink()
                    subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "compare_pdp_jiomart.py"), pin],
                                 cwd=str(PROJECT_ROOT), env=env, capture_output=True)

                # Stage 2-3
                _log(f"🔗 {city} {plat}: Stage 2-3 cascade...")
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "cascade_match.py"), pin, plat],
                             cwd=str(PROJECT_ROOT), env=env, capture_output=True)
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "stage3_match.py"), pin, plat],
                             cwd=str(PROJECT_ROOT), env=env, capture_output=True)

                # Stage 4: Search (Jiomart)
                if plat == "jiomart":
                    _log(f"🔎 {city} Jiomart: Stage 4 search...")
                    subprocess.run([VENV_PYTHON, str(PROJECT_ROOT / "scripts" / "jiomart_search_match.py"), pin],
                                 cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)

                # Stage 5: Image + Barcode
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "stage4_image_match.py"), pin, plat],
                             cwd=str(PROJECT_ROOT), env=env, capture_output=True)
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "stage5_barcode_match.py"), pin, plat],
                             cwd=str(PROJECT_ROOT), env=env, capture_output=True)

                _log(f"✅ {city} {plat}: Done!")

        # Generate Excel
        _log("📊 Generating Excel reports...")
        subprocess.run([VENV_PYTHON, str(PROJECT_ROOT / "scripts" / "daily_report.py"), "all", "--no-scrape"],
                     cwd=str(PROJECT_ROOT / "backend"), env=env, capture_output=True)

        _log("🎉 Pipeline complete!")
        _state["last_result"] = "success"

    except Exception as e:
        _log(f"❌ Error: {str(e)[:100]}")
        _state["last_result"] = f"error: {str(e)[:100]}"
    finally:
        _state["running"] = False
        _state["completed_at"] = datetime.now().isoformat()


@router.post("/run")
def run_pipeline(req: PipelineRequest, background_tasks: BackgroundTasks):
    """Trigger pipeline run with selected cities + platforms."""
    if _state["running"]:
        return {"status": "already_running", "started_at": _state["started_at"]}

    background_tasks.add_task(_run_pipeline, req.cities, req.platforms)
    return {"status": "started", "cities": req.cities, "platforms": req.platforms}


@router.get("/status")
def pipeline_status():
    """Get current pipeline status + progress."""
    return {
        "running": _state["running"],
        "started_at": _state["started_at"],
        "completed_at": _state["completed_at"],
        "config": _state["config"],
        "progress": _state["progress"][-20:],
        "last_result": _state["last_result"],
    }


@router.get("/schedule")
def get_schedule():
    """Get current schedule config."""
    return _state["schedule"]


@router.post("/schedule")
def set_schedule(req: ScheduleRequest):
    """Set schedule config."""
    _state["schedule"] = {
        "enabled": req.enabled,
        "time": req.time,
        "cities": req.cities,
        "platforms": req.platforms,
    }
    return {"status": "updated", "schedule": _state["schedule"]}


@router.get("/cities")
def get_cities():
    """Get available cities."""
    return {"cities": [{"pincode": p, "name": n} for p, n in CITIES.items()]}
