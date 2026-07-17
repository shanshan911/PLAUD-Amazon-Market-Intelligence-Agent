from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Start PLAUD MVP platform in the background")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="8501")
    parser.add_argument("--pid-file", default="outputs/platform_server.pid")
    parser.add_argument("--log-file", default="outputs/platform_server.log")
    parser.add_argument("--env-file", default=".env.local", help="Optional local env file for API secrets")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    pid_file = root / args.pid_file
    log_file = root / args.log_file
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log = log_file.open("ab")
    env = os.environ.copy()
    env.update(load_env_file(root / args.env_file))
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--host", args.host, "--port", str(args.port)],
        cwd=root,
        env=env,
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(1)
    if proc.poll() is not None:
        pid_file.unlink(missing_ok=True)
        print(f"PLAUD MVP platform failed to start on {args.host}:{args.port}.")
        print(f"Log: {log_file}")
        try:
            tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        except OSError:
            tail = []
        if tail:
            print("Recent log:")
            print("\n".join(tail))
        return int(proc.returncode or 1)
    print(f"Started PLAUD MVP platform at http://{args.host}:{args.port}")
    print(f"PID: {proc.pid}")
    print(f"Log: {log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
