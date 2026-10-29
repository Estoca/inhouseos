"""Settings, all from IHO_* environment variables."""
from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthMode(StrEnum):
    # One fixed bearer token mapped to one person. For a laptop or a test box only.
    DEV = "dev"
    # The server is its own OAuth authorization server, login through Google or Microsoft (LAB-53).
    STANDALONE = "standalone"
    # Behind inhouse.technology: trusts the actor token the iht gateway signs (milestone 3).
    IHT = "iht"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IHO_", env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    public_url: str = "http://localhost:8080"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    auth_mode: AuthMode = AuthMode.DEV
    dev_token: str = ""
    dev_user: str = ""

    @model_validator(mode="after")
    def _check_auth(self) -> Settings:
        if self.auth_mode is AuthMode.DEV:
            if not self.dev_token or not self.dev_user:
                raise ValueError("auth_mode=dev needs IHO_DEV_TOKEN and IHO_DEV_USER.")
            if len(self.dev_token) < 24:
                raise ValueError("IHO_DEV_TOKEN must have at least 24 characters.")
            if "@" not in self.dev_user:
                raise ValueError("IHO_DEV_USER must be an email address.")
        else:
            raise ValueError(f"auth_mode={self.auth_mode} is not implemented yet; use dev.")
        return self

    @property
    def normalized_public_url(self) -> str:
        return self.public_url.rstrip("/")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "iho.db"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"


@lru_cache
def get_settings() -> Settings:
    return Settings()
