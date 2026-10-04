from langchain_google_genai import ChatGoogleGenerativeAI

from chatbot.config import Settings


def create_chat_model(settings: Settings) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        vertexai=False,
        include_thoughts=settings.gemini_include_thoughts,
        thinking_level=settings.gemini_thinking_level,
        max_retries=settings.gemini_max_retries,
        timeout=settings.gemini_timeout_seconds,
    )
