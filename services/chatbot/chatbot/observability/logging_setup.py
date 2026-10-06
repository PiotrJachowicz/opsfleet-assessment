"""Application logging via the stdlib ``logging`` package.

Prototype sink: rotating file under ``output/logs`` (gitignored) plus console.
Production (see HLD): keep the same logger API and swap the file handler for a
GCP Cloud Logging handler / stdout JSON sink — no call-site changes required.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from chatbot.config import Settings

_FILE_HANDLER_NAME = "opsfleet_file"


def _resolve_logs_dir(settings: Settings) -> Path:
    path = Path(settings.logs_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging(settings: Settings) -> Path:
    """Attach a rotating file sink (idempotent) and set levels.

    Console/access logging stays with the process runner (uvicorn). Application
    loggers write to both the root handlers uvicorn already installed and this
    file sink.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logs_dir = _resolve_logs_dir(settings)
    log_path = logs_dir / settings.log_file_name

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    existing = next(
        (h for h in root.handlers if getattr(h, "name", None) == _FILE_HANDLER_NAME),
        None,
    )
    if existing is None:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        file_handler.set_name(_FILE_HANDLER_NAME)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    else:
        existing.setLevel(level)

    if not any(
        isinstance(h, logging.StreamHandler)
        and getattr(h, "name", None) != _FILE_HANDLER_NAME
        for h in root.handlers
    ):
        stream = logging.StreamHandler()
        stream.setLevel(level)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "chatbot"):
        logging.getLogger(name).setLevel(level)

    logging.getLogger(__name__).info(
        "logging configured level=%s file=%s "
        "(prototype file sink; production uses GCP Cloud Logging)",
        settings.log_level.upper(),
        log_path,
    )
    return log_path
