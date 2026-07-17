from app.core.config import settings


def pytest_sessionstart(session) -> None:
    settings.app_env = "test"
    settings.allow_fixture_llm = True
    settings.openai_api_key = None
