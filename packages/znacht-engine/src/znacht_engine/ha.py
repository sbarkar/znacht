"""Talk to Home Assistant: actionable notifications and events. Nothing else."""

from __future__ import annotations

import httpx

from znacht.ports.notify import PlanEvent


class HaNotifier:
    name = "home-assistant"

    def __init__(
        self, url: str, token: str, service: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._service = service
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def notify(self, event: PlanEvent) -> None:
        payload = {
            "title": event.title,
            "message": event.message,
            "data": {
                "tag": f"znacht-{event.kind}",
                "url": event.data.get("url"),
                "clickAction": event.data.get("url"),
                "actions": [
                    {
                        "action": f"ZNACHT_{a.upper()}",
                        "title": a.capitalize(),
                        **(
                            {"uri": event.data["url"]}
                            if a == "review" and event.data.get("url")
                            else {}
                        ),
                    }
                    for a in event.actions
                ],
            },
        }
        await self._client.post(
            f"{self._url}/api/services/notify/{self._service}",
            json=payload,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        await self._client.post(
            f"{self._url}/api/events/znacht_{event.kind}",
            json=dict(event.data),
            headers={"Authorization": f"Bearer {self._token}"},
        )
