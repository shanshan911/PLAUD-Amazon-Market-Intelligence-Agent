from __future__ import annotations

import json
from typing import Any

from .base import ApiRequestError, build_url, http_json, require_env


class SellerSpriteMcpClient:
    """Minimal SellerSprite MCP Streamable HTTP client."""

    def __init__(
        self,
        secret_key: str,
        endpoint: str = "https://mcp.sellersprite.com/mcp",
        timeout_seconds: int = 30,
    ) -> None:
        self.secret_key = secret_key
        self.endpoint = endpoint
        self.timeout_seconds = int(timeout_seconds or 30)
        self._next_id = 1

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SellerSpriteMcpClient":
        cfg = config.get("api_integrations", {}).get("sellersprite", {})
        return cls(
            secret_key=require_env(cfg, "secret_key_env"),
            endpoint=str(cfg.get("mcp_url") or "https://mcp.sellersprite.com/mcp"),
            timeout_seconds=int(cfg.get("timeout_seconds") or 30),
        )

    def headers(self) -> dict[str, str]:
        return {
            "secret-key": self.secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    def initialize(self) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "plaud-monitor", "version": "0.1"},
            },
        )

    def tools_list(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list):
            raise ApiRequestError("SellerSprite MCP tools/list returned invalid tools payload")
        return tools

    def tools_call(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        self._next_id += 1
        response = http_json("POST", self.endpoint, self.headers(), payload, self.timeout_seconds)
        if not isinstance(response, dict):
            raise ApiRequestError(f"SellerSprite MCP {method} returned non-object response")
        if response.get("error"):
            raise ApiRequestError(f"SellerSprite MCP {method} failed: {response['error']}")
        return response.get("result", {})


def parse_tool_content(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return result
    first = content[0]
    if not isinstance(first, dict):
        return result
    text = first.get("text")
    if not isinstance(text, str):
        return result
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
