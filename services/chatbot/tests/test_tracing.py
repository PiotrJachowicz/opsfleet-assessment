from chatbot.config import Settings
from chatbot.observability import configure_langsmith


def test_configure_langsmith_noop_without_key() -> None:
    configure_langsmith(
        Settings(
            langsmith_tracing=True,
            langsmith_api_key="",
        )
    )


def test_configure_langsmith_noop_when_disabled() -> None:
    configure_langsmith(
        Settings(
            langsmith_tracing=False,
            langsmith_api_key="abc",
        )
    )
