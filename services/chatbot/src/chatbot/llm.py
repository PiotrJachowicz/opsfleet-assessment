from langchain_google_genai import ChatGoogleGenerativeAI

from chatbot.config import Settings


def create_chat_model(settings: Settings) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        vertexai=False,
    )
