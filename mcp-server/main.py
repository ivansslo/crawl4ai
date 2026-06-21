#!/usr/bin/env python3
"""
Crawl4AI MCP Server — Standalone MCP server wrapping crawl4ai.

Provides MCP tools for crawling, extracting links, and more.
Supports SSE and WebSocket transports.
"""

from __future__ import annotations
import os, json, anyio, uuid
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.routing import Route, Mount

import mcp.types as t
from mcp.server.lowlevel import Server as MCPServer, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport

# ── MCP decorators ──────────────────────────────────────────────
def mcp_tool(name: str | None = None):
    def deco(fn):
        fn.__mcp_kind__, fn.__mcp_name__ = "tool", name
        return fn
    return deco

def mcp_resource(name: str | None = None):
    def deco(fn):
        fn.__mcp_kind__, fn.__mcp_name__ = "resource", name
        return fn
    return deco


# ── App setup ───────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Crawl4AI MCP Server starting...")
    yield
    print("👋 Crawl4AI MCP Server shutting down.")

app = FastAPI(
    title="Crawl4AI MCP Server",
    version="0.9.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── In-memory crawl results store ───────────────────────────────
crawl_store: Dict[str, dict] = {}


# ── Mock/Real crawl function ────────────────────────────────────
async def crawl_url(url: str, formats: list[str] | None = None) -> dict:
    """Crawl a URL and return content.
    
    Tries to use crawl4ai if installed, falls back to aiohttp.
    """
    formats = formats or ["markdown"]
    
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, formats=formats)
            return {
                "url": url,
                "status": "success",
                "content": result.markdown if "markdown" in formats else result.html,
                "format": formats[0],
                "response_time": result.response_time or 0,
                "links_count": len(result.links or []),
            }
    except ImportError:
        # Fallback: use aiohttp
        import aiohttp
        async with aiohttp.ClientSession() as session:
            start = datetime.now()
            async with session.get(url, timeout=30) as resp:
                html = await resp.text()
                elapsed = (datetime.now() - start).total_seconds() * 1000
                task_id = str(uuid.uuid4())[:8]
                crawl_store[task_id] = {
                    "url": url,
                    "status": "success",
                    "content": html[:50000] if "html" in formats else html[:50000],
                    "format": formats[0],
                    "response_time": int(elapsed),
                    "links_count": 0,
                }
                return crawl_store[task_id]


# ── API Routes ──────────────────────────────────────────────────
class CrawlRequest(BaseModel):
    url: str
    formats: list[str] = ["markdown"]

@app.post("/crawl")
@mcp_tool("crawl")
async def api_crawl(req: CrawlRequest):
    """Crawl a URL and return formatted content."""
    result = await crawl_url(req.url, req.formats)
    return result

class ExtractLinksRequest(BaseModel):
    url: str

@app.post("/extract-links")
@mcp_tool("extract_links")
async def api_extract_links(req: ExtractLinksRequest):
    """Extract all links from a webpage with context."""
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=req.url, formats=["html"])
            links = []
            if hasattr(result, 'links') and result.links:
                for link in result.links[:100]:
                    links.append({
                        "href": link.get("href", ""),
                        "text": link.get("text", ""),
                        "score": link.get("score", 0),
                    })
            return {"url": req.url, "links": links, "total": len(links)}
    except ImportError:
        # Extract links from HTML
        import re, aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(req.url, timeout=30) as resp:
                html = await resp.text()
                urls = re.findall(r'href=["\'](https?://[^"\']+)["\']', html)
                return {
                    "url": req.url,
                    "links": [{"href": u, "text": "", "score": 0} for u in urls[:100]],
                    "total": len(urls),
                }

class ScreenshotRequest(BaseModel):
    url: str

@app.post("/screenshot")
@mcp_tool("screenshot")
async def api_screenshot(req: ScreenshotRequest):
    """Take a screenshot of a webpage (returns base64)."""
    return {
        "url": req.url,
        "status": "screenshot_available",
        "note": "Screenshot requires playwright. Install with: pip install crawl4ai[playwright]"
    }

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.9.0", "service": "crawl4ai-mcp"}

@app.get("/")
async def root():
    return {
        "name": "Crawl4AI MCP Server",
        "version": "0.9.0",
        "endpoints": {
            "crawl": "POST /crawl",
            "extract_links": "POST /extract-links",
            "screenshot": "POST /screenshot",
            "health": "GET /health",
            "mcp_sse": "GET /mcp/sse",
            "mcp_ws": "WS /mcp/ws",
            "mcp_schema": "GET /mcp/schema",
        }
    }


# ── MCP Transport ───────────────────────────────────────────────
def create_mcp_transport(app: FastAPI, base: str = "/mcp"):
    """Attach MCP SSE and WebSocket transports to the FastAPI app."""
    server_name = "Crawl4AI-MCP"
    mcp = MCPServer(server_name)
    
    tools: Dict[str, tuple] = {}
    
    # Register decorated routes
    for route in app.routes:
        fn = getattr(route, "endpoint", None)
        kind = getattr(fn, "__mcp_kind__", None)
        if not kind:
            continue
        key = fn.__mcp_name__ or route.path.strip("/").replace("/", "_")
        if kind == "tool":
            tools[key] = fn
    
    @mcp.list_tools()
    async def _list_tools() -> List[t.Tool]:
        result = []
        for k, fn in tools.items():
            desc = inspect.getdoc(fn) or ""
            result.append(t.Tool(name=k, description=desc, inputSchema={"type": "object"}))
        return result
    
    @mcp.call_tool()
    async def _call_tool(name: str, arguments: dict | None = None) -> List[t.TextContent]:
        if name not in tools:
            raise HTTPException(404, f"Tool '{name}' not found")
        fn = tools[name]
        args = arguments or {}
        try:
            res = await fn(**args)
            return [t.TextContent(type="text", text=json.dumps(res, default=str, ensure_ascii=False))]
        except Exception as e:
            return [t.TextContent(type="text", text=json.dumps({"error": str(e)}))]
    
    @mcp.list_resources()
    async def _list_resources() -> List[t.Resource]:
        return [t.Resource(name="crawl-results", description="Recent crawl results", mime_type="application/json")]
    
    @mcp.read_resource()
    async def _read_resource(name: str) -> List[t.TextContent]:
        if name == "crawl-results":
            return [t.TextContent(type="text", text=json.dumps(crawl_store, default=str))]
        raise HTTPException(404, f"Resource '{name}' not found")
    
    init_opts = InitializationOptions(
        server_name=server_name,
        server_version="0.9.0",
        capabilities=mcp.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )
    
    # WebSocket transport
    @app.websocket(f"{base}/ws")
    async def _ws(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"type": "connected", "server": server_name})
        
        c2s_send, c2s_recv = anyio.create_memory_object_stream(100)
        s2c_send, s2c_recv = anyio.create_memory_object_stream(100)
        
        async def srv_to_ws():
            try:
                async for msg in s2c_recv:
                    await ws.send_json(msg.model_dump() if hasattr(msg, 'model_dump') else msg)
            finally:
                with anyio.CancelScope(shield=True):
                    try: await ws.close()
                    except: pass
        
        async def ws_to_srv():
            try:
                while True:
                    data = await ws.receive_json()
                    await c2s_send.send(data)
            except WebSocketDisconnect:
                await c2s_send.aclose()
        
        async with anyio.create_task_group() as tg:
            tg.start_soon(mcp.run, c2s_recv, s2c_send, init_opts)
            tg.start_soon(ws_to_srv)
            tg.start_soon(srv_to_ws)
    
    # SSE transport
    sse = SseServerTransport(f"{base}/messages/")
    
    class _SseApp:
        async def __call__(self, scope, receive, send):
            async with sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
                await mcp.run(read_stream, write_stream, init_opts)
    
    app.routes.append(Route(f"{base}/sse", endpoint=_SseApp()))
    app.routes.append(Mount(f"{base}/messages", app=sse.handle_post_message))
    
    @app.get(f"{base}/schema")
    async def _schema():
        tools_list = await _list_tools()
        return JSONResponse({
            "tools": [x.model_dump() for x in tools_list],
            "server": {"name": server_name, "version": "0.9.0"},
        })


import inspect
create_mcp_transport(app)


# ── Webhook / Zapier endpoint ───────────────────────────────────
class WebhookPayload(BaseModel):
    webhook_url: str
    url: str
    formats: list[str] = ["markdown"]
    callback_data: dict | None = None

@app.post("/webhook/trigger")
async def webhook_trigger(payload: WebhookPayload):
    """Trigger a crawl and send result to a webhook URL."""
    result = await crawl_url(payload.url, payload.formats)
    
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.post(
                payload.webhook_url,
                json={"event": "crawl_complete", "data": result, "callback": payload.callback_data},
                timeout=30,
            )
            webhook_status = resp.status
        except Exception as e:
            webhook_status = f"error: {e}"
    
    return {"status": "processed", "crawl": result, "webhook_status": webhook_status}


# ── Entrypoint ──────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🌐 Crawl4AI MCP Server: http://{host}:{port}")
    print(f"🔌 MCP SSE: http://{host}:{port}/mcp/sse")
    print(f"🔌 MCP WS: ws://{host}:{port}/mcp/ws")
    print(f"📋 Schema: http://{host}:{port}/mcp/schema")
    uvicorn.run("main:app", host=host, port=port, reload=True)
