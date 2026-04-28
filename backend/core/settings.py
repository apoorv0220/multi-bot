import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_host: str
    api_port: int
    cors_allow_origins: list[str]
    cors_allow_credentials: bool
    cors_allow_methods: list[str]
    cors_allow_headers: list[str]
    environment: str


def _parse_csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or ["*"]


def get_settings() -> Settings:
    return Settings(
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", 8043)),
        cors_allow_origins=_parse_csv(os.getenv("CORS_ALLOWED_ORIGINS", "*")),
        cors_allow_credentials=os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true",
        cors_allow_methods=_parse_csv(os.getenv("CORS_ALLOW_METHODS", "*")),
        cors_allow_headers=_parse_csv(os.getenv("CORS_ALLOW_HEADERS", "*")),
        environment=os.getenv("ENVIRONMENT", "development"),
    )
