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

    # Local embedding model, served by the same OpenAI-compatible endpoint.
    embedding_model: str = "nomic-embed-text"

    # Vision model for scanned documents and photographs.
    #
    # qwen2.5vl rather than llava. llava:7b was tried first and cannot read
    # dense documents at all: given a synthetic inspection scan it invented a
    # NASA equipment satisfaction report, and it hallucinated just as
    # confidently on a cropped three-line strip, so it is not a resolution
    # problem that preprocessing or tiling could fix. Its vision encoder is
    # built for describing photographs, not for reading pages.
    #
    # qwen2.5vl:7b transcribes the same scan exactly — every equipment tag,
    # measurement and line. On an inspection report a fluent invention is far
    # worse than a refusal, so the model that reads is the one that ships.
    vision_model: str = "qwen2.5vl:7b"

    # Vision runs a model over a rendered page image, which is slower than a
    # text turn — a cold llava load plus a full page can exceed the default.
    vision_request_timeout_seconds: float = 600.0

    # Cap on PDF pages processed in one upload. Each page is a separate model
    # call, so an unbounded document would occupy the only local GPU for a
    # very long time.
    vision_max_pages: int = 5

    # Largest upload accepted, in bytes. Rejected before the file is read into
    # memory rather than after.
    max_upload_bytes: int = 25 * 1024 * 1024

    # Ask the model for a short thread title instead of truncating the first
    # message. Better titles, at the cost of one extra call on the first turn
    # of a conversation; turn it off to save that latency.
    thread_titles_from_model: bool = True

    # Prior turns replayed to the model so follow-up questions resolve. Kept
    # small on purpose: the whole history is re-sent with every request, and a
    # long one both slows generation and crowds out retrieved context.
    max_history_messages: int = 8

    # Each replayed message is truncated to this. A previous answer only needs
    # to supply the antecedent for "it" or "that", not be reproduced in full.
    max_history_chars: int = 1200

    # How many chunks retrieval returns per question.
    rag_top_k: int = 4

    # Cosine-distance ceiling for a chunk to count as relevant. Chunks above
    # this are discarded rather than shown, which is what stops an unrelated
    # question from citing a document it has nothing to do with.
    #
    # Measured against the sample corpus rather than guessed. Four on-topic
    # questions scored 0.260-0.314; four off-topic ones scored 0.518-0.693.
    # This sits in the gap, with margin on both sides. An earlier guess of
    # 0.55 would have let "write a haiku about the sea" (0.518) cite an SOP.
    # Re-measure with scripts/ingest_samples.py output if the corpus or the
    # embedding model changes.
    rag_max_distance: float = 0.45

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
