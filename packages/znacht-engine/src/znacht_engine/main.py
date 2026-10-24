from __future__ import annotations

import uvicorn

from znacht_engine.app import create_app
from znacht_engine.config import EngineSettings


def main() -> None:
    settings = EngineSettings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
