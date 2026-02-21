from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""

    # Google Drive
    google_service_account_file: str = "service-account.json"
    google_drive_folder_id: str = ""

    # SendGrid
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""
    sendgrid_from_name: str = "Recruiting Team"
    sendgrid_unsubscribe_group_id: int = 0

    # App
    app_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./cvchecker.db"
    secret_key: str = "change-me"
    admin_api_key: str = "admin"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
