from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop PLAUD MVP platform")
    parser.add_argument("--pid-file", default="outputs/platform_server.pid")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    pid_file = root / args.pid_file
    if not pid_file.exists():
        print("No PID file found.")
        return 0
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped PID {pid}")
    except ProcessLookupError:
        print(f"PID {pid} is not running.")
    pid_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
