"""MCP (Model Context Protocol) bridge.

Lets iAgent use any MCP-compliant server as if its tools were native.
On startup we spawn each configured server, list its tools via
`tools/list`, and register every tool dynamically with the iAgent
registry. Tool names are prefixed with the server alias so they don't
collide.

Configure in config.json:

  "mcp_servers": [
    {"name": "ios", "command": "/var/jb/usr/bin/ios-mcp"},
    {"name": "web", "command": "node", "args": ["/path/to/server.js"]}
  ]

MCP wire format is JSON-RPC 2.0 over stdio. Each request/response is one
line of JSON. We follow the 2024-11-05 spec which is what most servers
ship today.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import tools.registry as registry

logger = logging.getLogger("iagent.mcp")

_PROTOCOL_VERSION = "2024-11-05"


class MCPClient:
    """One persistent stdio connection to an MCP server."""

    def __init__(self, name: str, command: str, args: Optional[list] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._lock = asyncio.Lock()
        self._tools: list[dict] = []

    async def start(self) -> None:
        try:
            self.proc = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"MCP server '{self.name}': command not found ({self.command})") from e

        # Initialize handshake
        await self._call("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "iAgent", "version": "1.0"},
        })
        # Some servers expect the notification too
        await self._notify("notifications/initialized", {})

        # Discover tools
        result = await self._call("tools/list", {})
        self._tools = result.get("tools", [])
        logger.info("MCP '%s' connected — %d tools discovered", self.name, len(self._tools))

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass

    async def _send(self, payload: dict) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError(f"MCP '{self.name}' not started")
        line = (json.dumps(payload) + "\n").encode()
        self.proc.stdin.write(line)
        await self.proc.stdin.drain()

    async def _read_response(self, expect_id: int, timeout: float = 30.0) -> dict:
        if not self.proc or not self.proc.stdout:
            raise RuntimeError(f"MCP '{self.name}' has no stdout")
        # Skip notifications until we see our reply
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"MCP '{self.name}' timed out")
            raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout=remaining)
            if not raw:
                raise RuntimeError(f"MCP '{self.name}' closed stdout")
            try:
                msg = json.loads(raw.decode())
            except json.JSONDecodeError:
                continue
            if msg.get("id") == expect_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result", {})
            # else: notification or unrelated reply, skip

    async def _call(self, method: str, params: Optional[dict] = None) -> dict:
        async with self._lock:
            self._req_id += 1
            rid = self._req_id
            await self._send({
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params or {},
            })
            return await self._read_response(rid)

    async def _notify(self, method: str, params: Optional[dict] = None) -> None:
        async with self._lock:
            await self._send({
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            })

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        result = await self._call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # MCP returns content as list of {type, text|...} blocks
        contents = result.get("content", [])
        parts = []
        for c in contents:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "image":
                parts.append(f"[image: {len(c.get('data', ''))} bytes base64]")
            else:
                parts.append(json.dumps(c))
        return "\n".join(parts) or "(no content)"

    @property
    def tools(self) -> list[dict]:
        return self._tools


# Module-level registry of started clients so handlers can reach them
_clients: dict[str, MCPClient] = {}


def _make_handler(client: MCPClient, mcp_tool_name: str):
    async def handler(**kwargs) -> str:
        try:
            return await client.call_tool(mcp_tool_name, kwargs)
        except Exception as exc:
            logger.exception("MCP call failed")
            return f"[mcp:{client.name}.{mcp_tool_name} error] {exc}"
    return handler


def _register_mcp_tool(client: MCPClient, tool: dict) -> None:
    """Map one MCP tool definition into an iAgent tool registration."""
    mcp_name = tool.get("name", "")
    if not mcp_name:
        return
    # Prefix to avoid collisions (e.g. "ios_tap", "web_fetch")
    iagent_name = f"{client.name}_{mcp_name}".replace("-", "_")
    description = tool.get("description", f"MCP tool {mcp_name} from {client.name}")
    # MCP gives a JSON Schema directly under inputSchema
    schema = tool.get("inputSchema") or {"type": "object", "properties": {}}

    handler = _make_handler(client, mcp_name)
    # Manually patch into registry without using the decorator (we don't have
    # a function-with-decorator at module load time — these are dynamic)
    registry._schemas.append({
        "type": "function",
        "function": {
            "name": iagent_name,
            "description": description[:1024],
            "parameters": schema,
        },
    })
    registry._handlers[iagent_name] = handler
    logger.info("Registered MCP tool: %s", iagent_name)


async def start_servers(config: list[dict]) -> None:
    """Start every MCP server in the config list and register its tools."""
    for entry in config:
        name = entry.get("name") or entry.get("command", "mcp")
        command = entry.get("command")
        args = entry.get("args", [])
        if not command:
            logger.warning("MCP entry missing command: %s", entry)
            continue
        client = MCPClient(name=name, command=command, args=args)
        try:
            await client.start()
        except Exception as exc:
            logger.warning("MCP '%s' failed to start: %s", name, exc)
            continue
        _clients[name] = client
        for tool in client.tools:
            _register_mcp_tool(client, tool)


async def stop_all() -> None:
    for client in _clients.values():
        try:
            await client.stop()
        except Exception:
            logger.exception("MCP shutdown failed")
    _clients.clear()
