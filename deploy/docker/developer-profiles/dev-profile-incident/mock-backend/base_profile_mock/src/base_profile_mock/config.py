"""Environment-driven settings for the base-profile mock server."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

# The console and mock form one local development stack. Reuse the console's
# untracked DB/R2 settings while preserving explicitly exported shell values.
_incident_console = Path(__file__).resolve().parents[4] / "incident-console"
load_dotenv(_incident_console / ".env.local", override=False)
load_dotenv(_incident_console / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOCK_")

    port: int = 7777
    public_base_url: str = "http://127.0.0.1:7777"


settings = Settings()
