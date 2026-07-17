from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = "com.plaud.monitor.platform"
WATCHDOG_LABEL = "com.plaud.monitor.platform.watchdog"
AWAKE_LABEL = "com.plaud.monitor.keepawake"


def run(command: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return launch_agents_dir() / f"{LABEL}.plist"


def watchdog_plist_path() -> Path:
    return launch_agents_dir() / f"{WATCHDOG_LABEL}.plist"


def awake_plist_path() -> Path:
    return launch_agents_dir() / f"{AWAKE_LABEL}.plist"


def build_plist(root: Path, python_path: str, host: str, port: int) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            python_path,
            str(root / "scripts" / "run_platform_foreground.py"),
            "--host",
            host,
            "--port",
            str(port),
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(root / "outputs" / "platform_launch_agent.out.log"),
        "StandardErrorPath": str(root / "outputs" / "platform_launch_agent.err.log"),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }


def build_watchdog_plist(root: Path, python_path: str, port: int) -> dict[str, object]:
    return {
        "Label": WATCHDOG_LABEL,
        "ProgramArguments": [
            python_path,
            str(root / "scripts" / "platform_healthcheck.py"),
            "--url",
            f"http://127.0.0.1:{port}/?week_id=2026-W29",
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "StartInterval": 60,
        "StandardOutPath": str(root / "outputs" / "platform_watchdog.out.log"),
        "StandardErrorPath": str(root / "outputs" / "platform_watchdog.err.log"),
    }


def build_awake_plist(root: Path) -> dict[str, object]:
    return {
        "Label": AWAKE_LABEL,
        "ProgramArguments": [
            "/usr/bin/caffeinate",
            "-dimsu",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(root / "outputs" / "platform_keepawake.out.log"),
        "StandardErrorPath": str(root / "outputs" / "platform_keepawake.err.log"),
    }


def unload_existing(path: Path) -> None:
    uid = os.getuid()
    run(["launchctl", "bootout", f"gui/{uid}", str(path)])
    run(["launchctl", "remove", path.stem])


def install(path: Path, label: str) -> None:
    uid = os.getuid()
    run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], check=True)
    run(["launchctl", "enable", f"gui/{uid}/{label}"], check=True)
    run(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"], check=True)


def listening_pids(port: int) -> list[str]:
    result = run(["lsof", "-ti", f"tcp:{port}"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def uninstall(path: Path) -> int:
    unload_existing(path)
    watchdog_path = watchdog_plist_path()
    awake_path = awake_plist_path()
    unload_existing(watchdog_path)
    unload_existing(awake_path)
    path.unlink(missing_ok=True)
    watchdog_path.unlink(missing_ok=True)
    awake_path.unlink(missing_ok=True)
    print(f"Uninstalled {LABEL}, {WATCHDOG_LABEL}, and {AWAKE_LABEL}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the PLAUD platform macOS LaunchAgent")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    path = plist_path()
    watchdog_path = watchdog_plist_path()
    awake_path = awake_plist_path()
    if args.uninstall:
        return uninstall(path)

    pids = listening_pids(args.port)
    if pids:
        print(f"Port {args.port} is already in use by PID(s): {', '.join(pids)}")
        print(f"Stop the existing process first: lsof -ti tcp:{args.port} | xargs kill -9")
        return 2

    root.joinpath("outputs").mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    unload_existing(path)
    unload_existing(watchdog_path)
    unload_existing(awake_path)
    with path.open("wb") as handle:
        plistlib.dump(build_plist(root, args.python, args.host, args.port), handle, sort_keys=False)
    with watchdog_path.open("wb") as handle:
        plistlib.dump(build_watchdog_plist(root, args.python, args.port), handle, sort_keys=False)
    with awake_path.open("wb") as handle:
        plistlib.dump(build_awake_plist(root), handle, sort_keys=False)
    install(path, LABEL)
    install(watchdog_path, WATCHDOG_LABEL)
    install(awake_path, AWAKE_LABEL)
    print(f"Installed {LABEL}")
    print(f"Plist: {path}")
    print(f"Watchdog: {watchdog_path}")
    print(f"Keep awake: {awake_path}")
    print(f"URL: http://10.0.153.253:{args.port}/?week_id=2026-W29")
    print(f"Logs: {root / 'outputs' / 'platform_launch_agent.err.log'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
