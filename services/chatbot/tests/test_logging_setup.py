import logging
from pathlib import Path

from chatbot.config import Settings
from chatbot.observability import configure_logging


def test_configure_logging_writes_rotating_file(tmp_path: Path) -> None:
    settings = Settings(
        logs_dir=str(tmp_path / "logs"),
        log_file_name="test-chatbot.log",
        log_level="info",
        log_max_bytes=1_000_000,
        log_backup_count=2,
    )
    path = configure_logging(settings)
    assert path == tmp_path / "logs" / "test-chatbot.log"

    logging.getLogger("chatbot.tests.logging").info("hello from test")
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = path.read_text(encoding="utf-8")
    assert "hello from test" in text
    assert "logging configured" in text

    # Idempotent: second call does not duplicate the file handler.
    configure_logging(settings)
    file_handlers = [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "name", None) == "opsfleet_file"
    ]
    assert len(file_handlers) == 1
