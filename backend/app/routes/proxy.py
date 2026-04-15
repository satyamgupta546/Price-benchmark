"""Proxy management API — view pool status, add/remove proxies, health check."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.proxy import ProxyManager

router = APIRouter(prefix="/api/proxy")

# Global proxy manager instance
manager = ProxyManager()


class ProxyAdd(BaseModel):
    server: str
    username: str = ""
    password: str = ""
    label: str = ""
    proxy_type: str = "http"


@router.get("/status")
def proxy_status():
    """Get proxy pool status."""
    return manager.get_stats()


@router.post("/add")
def add_proxy(proxy: ProxyAdd):
    """Add a proxy to the pool."""
    p = manager.add_proxy(proxy.server, proxy.username, proxy.password, proxy.label, proxy.proxy_type)
    return {"status": "added", "proxy": p.to_dict()}


@router.delete("/remove")
def remove_proxy(server: str):
    """Remove a proxy by server URL."""
    manager.remove_proxy(server)
    return {"status": "removed", "server": server}


@router.post("/health-check")
async def health_check():
    """Run health check on all proxies."""
    await manager.health_check_all()
    return manager.get_stats()


@router.post("/re-enable")
def re_enable_all():
    """Re-enable all disabled proxies."""
    manager.re_enable_all()
    return manager.get_stats()


@router.post("/load-config")
def load_config():
    """Load proxies from config/proxies.json."""
    from pathlib import Path
    config_path = Path(__file__).parent.parent.parent.parent / "config" / "proxies.json"
    manager.load_from_file(str(config_path))
    return manager.get_stats()
