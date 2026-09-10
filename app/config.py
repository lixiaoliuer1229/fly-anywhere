from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost/fly_anywhere"
    AUTH_COOKIE_SECURE: bool = False  # HTTPS deployment: set true
    API_KEY: str = ""  # AviationStack or Amadeus API key
    API_SECRET: str = ""  # Amadeus API secret
    API_SOURCE: str = "aviationstack"  # aviationstack | amadeus
    SCRAPE_INTERVAL_HOURS: int = 24

    EMAIL_ENABLED: bool = False
    EMAIL_TO: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_SSL: bool = True  # False uses STARTTLS

    # AI 联网搜索。Tavily 负责检索网页，LLM 负责规划检索并整理结构化结果。
    TAVILY_API_KEY: str = ""
    SERPAPI_API_KEY: str = ""
    RAPIDAPI_KEY: str = ""
    AMADEUS_API_KEY: str = ""
    AMADEUS_API_SECRET: str = ""
    AMADEUS_BASE_URL: str = "https://test.api.amadeus.com"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    AI_MODEL: str = "gpt-4.1-mini"
    AI_PROVIDER: str = "openai"  # openai | anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str | None = None
    ANTHROPIC_MODEL: str = ""

    class Config:
        env_file = str(BASE_DIR / ".env")


settings = Settings()
