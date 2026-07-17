from __future__ import annotations

import argparse
import os
import subprocess
from urllib import request


SERVICE_LABEL = "com.plaud.monitor.platform"


def healthy(url: str, timeout: int) -> bool:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def restart_service() -> None:
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{uid}/{SERVICE_LABEL}"],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Health check the PLAUD platform and restart it if needed")
    parser.add_argument("--url", default="http://127.0.0.1:8501/?week_id=2026-W29")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    if healthy(args.url, args.timeout):
        print(f"healthy: {args.url}")
        return 0
    print(f"unhealthy, restarting: {args.url}")
    restart_service()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
