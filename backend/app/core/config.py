"""Runtime configuration for Drishti Workbench.

Every setting here must describe a host on the local machine or the local
Docker network. There is deliberately no API-key field: the workbench has no
cloud account to authenticate against, and adding one would break the
air-gapped guarantee the whole project is built on. Neither Ollama nor a
default vLLM deployment requires authentication, so none is needed.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base URL of the OpenAI-compatible model server, including the /v1 suffix.
    #
    # Points to Ollama for local Mac development/demo. For production
    # deployment on MRPL's GPU server, this URL points to a vLLM instance
    # instead — no other code changes required.
    #
    # Both engines expose the same /v1/chat/completions contract, which is the
    # only thing app.services.model_client depends on. Swapping engines is a
    # configuration change, not a code change:
    #
    #   Ollama (Mac dev):   http://localhost:11434/v1
    #   Ollama (compose):   http://ollama:11434/v1
    #   vLLM (MRPL GPU):    http://gpu-server.internal:8000/v1
    model_server_url: str = "http://localhost:11434/v1"

    # Models the router selects between. Ollama tags today; on vLLM these
    # become the served model names (e.g. "Qwen/Qwen2.5-7B-Instruct").
    reasoning_model: str = "qwen2.5:7b"
    coding_model: str = "qwen2.5-coder:7b"

    # Fallback when the router cannot choose and the caller names no model.
    default_model: str = "qwen2.5:7b"

    # Prepended to every conversation by ModelServingClient. Users never see
    # or set this. The language clause exists because Qwen2.5 will otherwise
    # drift into Chinese when a prompt does not establish a language.
    system_prompt: str = (
        "You are Drishti, an AI assistant for MRPL refinery staff. "
        "Always respond in English unless the user explicitly writes in "
        "another language."
    )

    # Generous ceiling: a cold model load on a laptop can take a while before
    # the first token appears.
    model_request_timeout_seconds: float = 300.0

    # Dev-server origins allowed to call this API from a browser.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


settings = Settings()
