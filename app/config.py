from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost/fly_anywhere"
    API_KEY: str = ""  # AviationStack or Amadeus API key
    API_SOURCE: str = "aviationstack"  # aviationstack | amadeus
    SCRAPE_INTERVAL_HOURS: int = 12

    class Config:
        env_file = ".env"


settings = Settings()
