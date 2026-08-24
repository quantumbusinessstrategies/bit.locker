from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class BrowserDriverStatus:
    available: bool
    driver: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrowserDriverInspection:
    attempted: bool
    reachable: bool
    url: str
    final_url: str
    title: str
    forms_found: int
    buttons_found: int
    cta_candidates: list[dict[str, str]]
    blocked_reason: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def browser_driver_status() -> BrowserDriverStatus:
    system_browser = _system_browser_executable()
    if system_browser is None:
        return BrowserDriverStatus(
            available=False,
            driver="Real Chrome/Edge",
            note="No real Chrome/Edge executable was found. Rendered-page probes are disabled; Requests/HTML inspection remains active.",
        )
    if importlib.util.find_spec("playwright") is None:
        return BrowserDriverStatus(
            available=False,
            driver="Real Chrome/Edge",
            note="Rendered-page control library is not installed. Requests/HTML inspection remains active.",
        )
    return BrowserDriverStatus(
        available=True,
        driver=f"Real Chrome/Edge ({system_browser.name})",
        note="JS-capable inspection uses the installed browser for Live Assist probes. It does not submit forms.",
    )


def inspect_with_playwright(url: str, timeout_ms: int = 12000) -> BrowserDriverInspection:
    if not _safe_http_url(url):
        return _inspection(
            attempted=False,
            reachable=False,
            url=url,
            blocked_reason="missing_or_invalid_url",
            note="URL is missing or is not an HTTP/HTTPS URL.",
        )

    status = browser_driver_status()
    if not status.available:
        return _inspection(
            attempted=False,
            reachable=False,
            url=url,
            blocked_reason="playwright_unavailable",
            note=status.note,
        )

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return _inspection(
            attempted=False,
            reachable=False,
            url=url,
            blocked_reason="playwright_import_failed",
            note=f"Playwright import failed: {exc.__class__.__name__}.",
        )

    browser = None
    try:
        system_browser = _system_browser_executable()
        if system_browser is None:
            return _inspection(
                attempted=False,
                reachable=False,
                url=url,
                blocked_reason="real_browser_unavailable",
                note="No real Chrome/Edge executable was found for rendered-page inspection.",
            )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(system_browser))
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(750)
            final_url = page.url
            title = page.title()
            forms_found = page.locator("form").count()
            buttons_found = page.locator("button, input[type=submit], a").count()
            cta_candidates = _cta_candidates_from_page(page)
            return BrowserDriverInspection(
                attempted=True,
                reachable=True,
                url=url,
                final_url=final_url,
                title=title,
                forms_found=forms_found,
                buttons_found=buttons_found,
                cta_candidates=cta_candidates,
                blocked_reason="",
                note="Playwright inspected the rendered page. No external form submission was attempted.",
            )
    except Exception as exc:  # noqa: BLE001
        return _inspection(
            attempted=True,
            reachable=False,
            url=url,
            blocked_reason="playwright_navigation_failed",
            note=f"Rendered browser inspection failed: {exc.__class__.__name__}.",
        )
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def _cta_candidates_from_page(page: Any) -> list[dict[str, str]]:
    terms = [
        "claim",
        "file claim",
        "apply",
        "request sample",
        "free sample",
        "redeem",
        "get started",
        "register",
        "join",
        "submit",
        "participate",
    ]
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    locators = page.locator("a, button, input[type=submit]")
    count = min(locators.count(), 160)
    for index in range(count):
        locator = locators.nth(index)
        try:
            text = " ".join(str(locator.inner_text(timeout=400) or locator.get_attribute("value") or "").split())
            href = locator.get_attribute("href") or ""
        except Exception:
            continue
        blob = f"{text} {href}".lower()
        if not any(term in blob for term in terms):
            continue
        key = f"{text}|{href}"
        if key in seen:
            continue
        seen.add(key)
        output.append({"label": text[:140] or "action", "url": href})
        if len(output) >= 12:
            break
    return output


def _inspection(
    *,
    attempted: bool,
    reachable: bool,
    url: str,
    blocked_reason: str,
    note: str,
) -> BrowserDriverInspection:
    return BrowserDriverInspection(
        attempted=attempted,
        reachable=reachable,
        url=url,
        final_url="",
        title="",
        forms_found=0,
        buttons_found=0,
        cta_candidates=[],
        blocked_reason=blocked_reason,
        note=note,
    )


def _safe_http_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _system_browser_executable() -> Path | None:
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
