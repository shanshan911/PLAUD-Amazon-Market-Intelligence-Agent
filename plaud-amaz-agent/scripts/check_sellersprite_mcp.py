from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plaud_monitor.config import load_config
from plaud_monitor.integrations.sellersprite_mcp import SellerSpriteMcpClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SellerSprite MCP and list available tools")
    parser.add_argument("--config", default="config/monitor_config.p0.json")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    root = Path(args.config).resolve().parents[1]
    load_env_file(root / args.env_file)
    config = load_config(args.config)
    client = SellerSpriteMcpClient.from_config(config)
    init_result = client.initialize()
    tools = client.tools_list()

    if args.json:
        print(json.dumps({"initialize": init_result, "tools": tools}, ensure_ascii=False, indent=2))
        return 0

    server = init_result.get("serverInfo", {}) if isinstance(init_result, dict) else {}
    print(f"SellerSprite MCP: {server.get('name', 'unknown')} {server.get('version', '')}".strip())
    print(f"Tools: {len(tools)}")
    for tool in tools[: args.limit]:
        name = tool.get("name", "")
        description = str(tool.get("description", "")).replace("\n", " ")
        print(f"- {name}: {description[:180]}")
    return 0


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
