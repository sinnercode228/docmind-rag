"""Application settings, loaded from environment variables (prefix ``DOCMIND_``) or ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["fake", "anthropic", "openai"]
EmbedderName = Literal["hashing", "openai"]
VectorStoreName = Literal["memory", "pgvector"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- runtime ---------------------------------------------------------------------------
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- storage ---------------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./docmind.db"
    vector_store: VectorStoreName = "memory"
    #: Directory for snapshotting the in-memory vector store between restarts (dev only).
    memory_store_path: str | None = None

    # --- auth ------------------------------------------------------------------------------
    #: If set, a tenant named ``default`` with this API key is created on startup (dev/demo).
    bootstrap_api_key: SecretStr | None = None
    #: Token protecting ``/v1/admin/*`` endpoints. Admin API is disabled when unset.
    admin_token: SecretStr | None = None

    # --- ingestion -------------------------------------------------------------------------
    chunk_size: int = 900
    chunk_overlap: int = 150
    max_upload_mb: int = 20
    ingest_workers: int = 2
    url_fetch_timeout_s: float = 15.0
    #: Allow ingesting URLs that resolve to private/loopback addresses (SSRF guard off).
    allow_private_urls: bool = False

    # --- embeddings ------------------------------------------------------------------------
    embedder: EmbedderName = "hashing"
    embedding_dim: int = 384
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: SecretStr | None = None
    embedding_batch_size: int = 64

    # --- retrieval -------------------------------------------------------------------------
    top_k: int = 5
    fetch_k: int = 24
    mmr_lambda: float = 0.6
    min_score: float = 0.05
    history_turns: int = 4

    # --- LLM -------------------------------------------------------------------------------
    llm_provider: LLMProviderName = "fake"
    llm_max_tokens: int = 4096
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5"
    #: Optional effort level (low/medium/high/xhigh/max). Unset = API default.
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    #: Server-side refusal fallbacks (beta). Recommended on; disable for providers without it.
    anthropic_fallbacks: bool = True
    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: SecretStr | None = None
    openai_model: str = "llama3.1"

    # --- telegram --------------------------------------------------------------------------
    telegram_bot_token: SecretStr | None = None
    #: Base URL of the DocMind API the bot talks to.
    telegram_api_url: str = "http://localhost:8000"
    telegram_api_key: SecretStr | None = None
    #: Optional allow-list of chat IDs (JSON list). Empty = the bot answers everyone.
    telegram_allowed_chat_ids: list[int] = Field(default_factory=list)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
