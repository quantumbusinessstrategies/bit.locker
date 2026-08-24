from __future__ import annotations

from typing import Any

from routing.destination_router import DestinationRouter


class AcceptanceQueue:
    def __init__(self, router: DestinationRouter | None = None) -> None:
        self.router = router or DestinationRouter()

    def normalize(self, item: dict[str, Any]) -> dict[str, str]:
        return self.router.route(item)

    def normalize_many(self, items: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [self.normalize(item) for item in items]

