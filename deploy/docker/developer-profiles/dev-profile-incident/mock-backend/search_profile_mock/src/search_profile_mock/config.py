"""Environment-driven settings for the search-profile mock server."""

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOCK_")

    port: int = 7778
    public_base_url: str = "http://localhost:7778"


settings = Settings()
