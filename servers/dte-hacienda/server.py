"""DTE MCP Server — operational visibility over an electronic-invoicing backend."""

import json
import logging
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dte-hacienda-mcp")

CONFIG_PATH = Path(__file__).parent / "config.json"


class DTEClient:
    """Async HTTP client with JWT auth for DTE Transmisor API."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        self.api_base = config["api_base"]
        self.email = config.get("email", "")
        self.password = config.get("password", "")
        self.access_token: str | None = None
        self.http = httpx.AsyncClient(timeout=15.0)

    async def _login(self):
        if not self.email or not self.password:
            raise ValueError("DTE credentials not configured. Edit config.json with email and password.")
        resp = await self.http.post(
            f"{self.api_base}/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data.get("access_token")

    async def request(self, method: str, path: str, **kwargs) -> dict | list | str:
        if not self.access_token:
            await self._login()

        url = f"{self.api_base}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        try:
            resp = await self.http.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 401:
                await self._login()
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = await self.http.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 404:
                return {"error": "Endpoint not available — may need to be added to DTE Transmisor API", "status": 404, "path": path}
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            return {"error": f"Cannot connect to {self.api_base} — service may be down"}
        except httpx.TimeoutException:
            return {"error": f"Timeout connecting to {self.api_base}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}


client = DTEClient()
mcp = FastMCP("dte-hacienda", instructions="Tools for monitoring an electronic-invoicing backend: transmission queue, tax-authority API health, and the document-signing service.")


def _format(data) -> str:
    if isinstance(data, dict) and "error" in data:
        return f"ERROR: {data['error']}"
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
async def dte_health_check() -> str:
    """Check health of DTE Transmisor — API, database, Redis, and Firmador status."""
    try:
        resp = await client.http.get(f"{client.api_base}/health", timeout=10.0)
        return _format(resp.json())
    except Exception as e:
        return f"HEALTH CHECK FAILED: {e}"


@mcp.tool()
async def dte_list_pending(status: str = "all") -> str:
    """List DTEs by status: pending, accepted, rejected, contingency, or all."""
    params = {} if status == "all" else {"status": status}
    result = await client.request("GET", "/api/v1/admin/dtes", params=params)
    return _format(result)


@mcp.tool()
async def dte_stats(period: str = "today") -> str:
    """Get DTE transmission statistics. Period: today, week, month."""
    result = await client.request("GET", f"/api/v1/admin/stats", params={"period": period})
    return _format(result)


@mcp.tool()
async def dte_retry_failed(dte_id: int) -> str:
    """Retry transmission of a failed DTE by its ID."""
    result = await client.request("POST", f"/api/v1/admin/dtes/{dte_id}/retry")
    return _format(result)


@mcp.tool()
async def dte_check_credentials(emisor_id: int) -> str:
    """Test Hacienda API credentials for an emisor. Verifies the login works."""
    result = await client.request("GET", f"/api/v1/admin/emisores/{emisor_id}/test-credentials")
    return _format(result)


@mcp.tool()
async def dte_contingency_status() -> str:
    """Check if the system is in contingency mode (offline invoicing)."""
    result = await client.request("GET", "/api/v1/admin/contingency/status")
    return _format(result)


@mcp.tool()
async def dte_firmador_status() -> str:
    """Check if the Firmador (digital signature) service is reachable."""
    try:
        resp = await client.http.get(f"{client.api_base}/api/v1/admin/firmador/status", timeout=10.0)
        return _format(resp.json())
    except Exception as e:
        return f"FIRMADOR CHECK FAILED: {e}"


if __name__ == "__main__":
    mcp.run()
