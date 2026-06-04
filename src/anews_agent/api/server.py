from __future__ import annotations

import uvicorn

from anews_agent.api.app import create_app
from anews_agent.config import AppConfig


def main() -> None:
    uvicorn.run(create_app(AppConfig.from_env()), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
