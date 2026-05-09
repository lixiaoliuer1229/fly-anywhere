from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost/fly_anywhere"
    API_KEY: str = ""  # AviationStack or Amadeus API key
    API_SECRET: str = ""  # Amadeus API secret
    API_SOURCE: str = "aviationstack"  # aviationstack | amadeus
    SCRAPE_INTERVAL_HOURS: int = 12

    class Config:
        env_file = str(BASE_DIR / ".env")


settings = Settings()
