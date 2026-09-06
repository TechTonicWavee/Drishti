"""Runtime configuration for Drishti Workbench.

Every setting here must describe a host on the local machine or the local
Docker network. There is deliberately no API-key field: the workbench has no
cloud account to authenticate against, and adding one would break the
air-gapped guarantee the whole project is built on.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base URL of the locally-running Ollama daemon. Used later for inference.
    # Host default; docker-compose overrides this to http://ollama:11434.
    ollama_host: str = "http://localhost:11434"

    # Dev-server origins allowed to call this API from a browser.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


settings = Settings()
