"""Process settings. Environment variables use the CCR_ prefix."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CCR_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/ccr_xva.db"
    chroma_path: str = "./data/chroma"
    pinecone_api_key: str | None = None
    pinecone_index: str = "ccr-methodology"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_embed_model: str = "llama-text-embed-v2"
    pinecone_namespace: str = "methodology"
    llm_enabled: bool = False
    agent: str = "adk"
    adk_model: str = "gemini-2.5-flash"
    google_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    api_url: str = "http://localhost:8000/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
