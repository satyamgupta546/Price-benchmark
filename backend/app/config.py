import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "development")
    HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
    SCRAPE_DELAY: int = int(os.getenv("SCRAPE_DELAY", "3"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    MAX_PRODUCTS_PER_PLATFORM: int = int(os.getenv("MAX_PRODUCTS_PER_PLATFORM", "10000"))
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")


settings = Settings()
