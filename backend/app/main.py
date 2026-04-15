from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.routes.scrape import router as scrape_router
from app.routes.sam import router as sam_router
from app.routes.proxy import router as proxy_router
from app.routes.pipeline import router as pipeline_router

app = FastAPI(
    title="Price Benchmark API",
    description="Quick Commerce Assortment Scraper — Blinkit, JioMart, Flipkart Minutes",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:6789", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrape_router, prefix="/api")
app.include_router(sam_router)
app.include_router(proxy_router)
app.include_router(pipeline_router)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Price Benchmark API"}


# Serve React frontend
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = FRONTEND_DIR / full_path
        # Prevent path traversal (e.g., ../../etc/passwd)
        if file_path.resolve().is_relative_to(FRONTEND_DIR.resolve()) and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
