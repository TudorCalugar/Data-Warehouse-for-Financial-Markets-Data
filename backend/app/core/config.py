from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongo_uri: str = "mongodb://acme:acme_secret@localhost:27017/acme_dwh?authSource=admin"
    mongo_db_name: str = "acme_dwh"

    # External data providers
    nasdaq_api_key: str = "demo"
    nasdaq_base_url: str = "https://data.nasdaq.com/api/v3"

    # App
    app_name: str = "Acme Ltd – Financial DWH"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    debug: bool = False

    # LLM (Anthropic)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
