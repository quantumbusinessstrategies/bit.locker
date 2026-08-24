from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    os.chdir(root)
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))

    from connectors.live_connector_sessions import (
        live_connector_profile_dir,
        provider_by_key,
        save_live_connector_status,
        utc_now,
    )

    provider = provider_by_key(args.provider)
    if provider is None:
        raise SystemExit(f"Unknown connector provider: {args.provider}")
    url = args.url or provider.login_url
    profile_dir = live_connector_profile_dir(root, provider.key)
    profile_dir.mkdir(parents=True, exist_ok=True)

    save_live_connector_status(
        root,
        provider.key,
        {
            "state": "launching",
            "pid": os.getpid(),
            "login_url": url,
            "profile_dir": str(profile_dir),
            "launched_at": utc_now(),
            "note": "Login browser launching. Owner should sign in manually if needed.",
        },
    )

    system_browser = _find_system_browser()
    if system_browser is not None:
        return _launch_system_browser(
            root=root,
            provider_key=provider.key,
            url=url,
            profile_dir=profile_dir,
            browser_path=system_browser,
            duration_seconds=args.duration_seconds,
            save_live_connector_status=save_live_connector_status,
            utc_now=utc_now,
        )

    save_live_connector_status(
        root,
        provider.key,
        {
            "state": "error",
            "login_url": url,
            "profile_dir": str(profile_dir),
            "note": "No real Chrome or Edge executable was found. Connector login was not opened in a test browser.",
        },
    )
    raise SystemExit("No real Chrome or Edge executable found for connector login.")


def _launch_system_browser(
    *,
    root: Path,
    provider_key: str,
    url: str,
    profile_dir: Path,
    browser_path: Path,
    duration_seconds: int,
    save_live_connector_status,
    utc_now,
) -> int:
    command = [
        str(browser_path),
        f"--user-data-dir={profile_dir}",
        "--new-window",
        "--no-first-run",
        "--disable-default-apps",
        url,
    ]
    process = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    save_live_connector_status(
        root,
        provider_key,
        {
            "state": "real_browser_open",
            "pid": process.pid,
            "browser": str(browser_path),
            "login_url": url,
            "profile_dir": str(profile_dir),
            "note": "Real Chrome/Edge login window opened. Sign in there, then close the window when done.",
        },
    )
    try:
        process.wait(timeout=duration_seconds)
        state = "profile_saved"
        note = "Real browser window closed. Connector profile saved locally; mark authorized after confirming login worked."
    except subprocess.TimeoutExpired:
        state = "login_window_still_open"
        note = "Real browser login window is still open. Finish login, then close it; the local connector profile will keep the session."
    save_live_connector_status(
        root,
        provider_key,
        {
            "state": state,
            "pid": process.pid,
            "browser": str(browser_path),
            "profile_dir": str(profile_dir),
            "last_closed_at": utc_now() if state == "profile_saved" else "",
            "note": note,
        },
    )
    return 0


def _find_system_browser() -> Path | None:
    for executable in ("chrome.exe", "chrome", "msedge.exe", "msedge"):
        found = shutil.which(executable)
        if found:
            return Path(found)

    candidate_strings = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for candidate in candidate_strings:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a persistent connector login browser profile.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
