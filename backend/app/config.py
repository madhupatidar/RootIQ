from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://ovpoc:ovpoc@localhost:5433/ovpoc"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_seconds: float = 120.0
    # Required for hosted Ollama Cloud (https://ollama.com); leave blank for a local daemon.
    ollama_api_key: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def model_identifier(self) -> str:
        return f"ollama:{self.ollama_model}"

    @property
    def ollama_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.ollama_api_key}"} if self.ollama_api_key else {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
