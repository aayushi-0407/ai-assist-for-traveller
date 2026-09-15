"""
Central place for environment/config values.

Import `settings` from here everywhere else in the app instead of reading
os.environ directly — when you're ready to wire up a real provider (Duffel,
Google Maps, etc.), add the key here once and every service picks it up.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
    duffel_api_key: str = os.environ.get("DUFFEL_API_KEY", "")
    hotels_api_key: str = os.environ.get("HOTELS_API_KEY", "")
    google_maps_api_key: str = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    google_calendar_client_id: str = os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "")
    google_calendar_client_secret: str = os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", "")
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ]


settings = Settings()
