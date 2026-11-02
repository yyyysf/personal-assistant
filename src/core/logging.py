"""统一日志配置：控制台 + 轮转文件，分级输出。"""

import logging
import logging.handlers
from pathlib import Path

from src.core.config import BASE_DIR, settings

LOG_DIR = BASE_DIR / "logs"
_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if settings.debug else logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)

    file_handler = logging.handlers.RotatingFileHandler(
        Path(LOG_DIR) / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
