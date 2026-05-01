from pydantic_settings import BaseSettings
from typing import List
from zoneinfo import ZoneInfo


class Settings(BaseSettings):
    SECRET_KEY: str = "change_me_to_random_secret_32_chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 дней

    DATABASE_URL: str = "./dental.db"
    TIMEZONE: str = "Asia/Almaty"  # UTC+5
    
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

    WHATSAPP_API_URL: str = "https://api.green-api.com"
    WHATSAPP_INSTANCE: str = ""
    WHATSAPP_TOKEN: str = ""

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:4173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
