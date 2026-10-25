from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EngineSettings:
    household_path: Path
    data_dir: Path
    recipe_source: str = "memory"
    store: str = "memory"
    sink: str = "memory"
    planner: str = "rule_based"
    api_token: str | None = None
    public_url: str = "http://localhost:8787"
    ha_url: str | None = None
    ha_token: str | None = None
    ha_notify_service: str | None = None  # e.g. "mobile_app_sergej" (without "notify.")
    host: str = "0.0.0.0"
    # The HA add-on: trust Home Assistant's ingress gateway and serve under its path (ADR-0012)
    ingress: bool = False
    # where notification links point instead of the Brief, e.g. the add-on's sidebar panel
    notify_link: str | None = None
    port: int = 8787
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> EngineSettings:
        e = os.environ if env is None else env
        data_dir = Path(e.get("ZNACHT_DATA_DIR", "~/.local/share/znacht")).expanduser()
        return cls(
            household_path=Path(
                e.get("ZNACHT_HOUSEHOLD", str(data_dir / "household.yaml"))
            ).expanduser(),
            data_dir=data_dir,
            recipe_source=e.get("ZNACHT_RECIPE_SOURCE", "memory"),
            store=e.get("ZNACHT_STORE", "memory"),
            sink=e.get("ZNACHT_SINK", "memory"),
            planner=e.get("ZNACHT_PLANNER", "rule_based"),
            api_token=e.get("ZNACHT_API_TOKEN") or None,
            public_url=e.get("ZNACHT_PUBLIC_URL", "http://localhost:8787").rstrip("/"),
            ha_url=(e.get("ZNACHT_HA_URL") or None),
            ha_token=e.get("ZNACHT_HA_TOKEN") or None,
            ha_notify_service=e.get("ZNACHT_HA_NOTIFY") or None,
            host=e.get("ZNACHT_HOST", "0.0.0.0"),
            ingress=e.get("ZNACHT_INGRESS", "").lower() in ("1", "true", "on"),
            notify_link=e.get("ZNACHT_NOTIFY_LINK") or None,
            port=int(e.get("ZNACHT_PORT", "8787")),
        )
