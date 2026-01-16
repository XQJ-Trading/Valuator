import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Config:
    agent_model: str
    google_api_key: str | None
    perplexity_api_key: str | None
    supported_models: tuple[str, ...]


def load_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    model = os.getenv("AGENT_MODEL", "gemini-3-flash-preview")
    supported = _split_csv(os.getenv("SUPPORTED_MODELS")) or (
        model,
        "gemini-3-pro-preview",
    )
    return Config(
        agent_model=model,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        perplexity_api_key=os.getenv("PPLX_API_KEY"),
        supported_models=tuple(dict.fromkeys(supported)),
    )


config = load_config()
