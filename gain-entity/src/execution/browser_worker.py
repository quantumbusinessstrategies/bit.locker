from __future__ import annotations

from typing import Any


class BrowserWorker:
    def prepare(self, item: dict[str, Any]) -> dict[str, Any]:
        official_link = str(item.get("official_link") or item.get("url") or "").strip()
        if not official_link:
            return {
                "worked": False,
                "summary": "No official link is available for browser continuation.",
                "next_action": "Find or confirm the official claim path before continuing.",
                "completion": 35,
            }
        return {
            "worked": True,
            "summary": "Official link is ready for browser-assisted public-page review.",
            "next_action": f"Open and inspect the official path: {official_link}",
            "completion": 65,
            "official_link": official_link,
        }

