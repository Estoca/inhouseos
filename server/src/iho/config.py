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

    # standalone login: the server is the OAuth server agents connect to; people sign in upstream
    oidc_provider: str = "google"  # google | oidc (any OpenID provider with discovery, e.g. a Microsoft tenant)
    oidc_issuer: str = "https://accounts.google.com"
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    allowed_domains: str = ""  # comma list: who signs in with a verified company e-mail
    allowed_emails: str = ""  # comma list: invited people from outside those domains
    # DCR is open (claude.ai needs it); only these hosts may receive codes, so a random site cannot
    # register itself and collect logins
    oauth_redirect_hosts: str = "claude.ai,claude.com,localhost,127.0.0.1"
    access_token_seconds: int = 3600
    refresh_token_days: int = 30

    # company values the skills are filled with (iho.skillbook): never written in the skill text
    company_name: str = ""
    company_domain: str = ""  # empty: the first of allowed_domains
    company_connectors: str = "Slack,Gmail,Google Calendar,Google Drive"  # what each person connects on their agent
    company_meeting_notes: str = ""  # official source of meeting notes, e.g. "Gemini notes in Google Drive"

    # scheduled snapshots (iho.backup); unset = off. Copying them off the machine is the operator's tool.
    backup_dir: Path | None = None
    backup_every_hours: float = 24
    backup_keep: int = 7

    # brains: limits ported from estoca-brain-sync 0.4.0
    link_ttl_seconds: int = 300
    max_files_per_upload: int = 200
    max_upload_bytes: int = 50_000_000
    max_file_bytes: int = 1_000_000
    max_files_per_push: int = 100
    max_files_per_pull: int = 200
    max_bytes_per_pull: int = 4_000_000
    pull_hint_bytes: int = 100_000
    snapshot_cache_repos: int = 32
    max_list_entries: int = 2000
    read_default_lines: int = 400
    max_read_bytes: int = 60_000
    search_default_results: int = 30
    max_search_results: int = 200
    max_search_context: int = 5
    max_line_chars: int = 300

    @model_validator(mode="after")
    def _check_auth(self) -> Settings:
        if self.auth_mode is AuthMode.DEV:
            if not self.dev_token or not self.dev_user:
                raise ValueError("auth_mode=dev needs IHO_DEV_TOKEN and IHO_DEV_USER.")
            if len(self.dev_token) < 24:
                raise ValueError("IHO_DEV_TOKEN must have at least 24 characters.")
            if "@" not in self.dev_user:
                raise ValueError("IHO_DEV_USER must be an email address.")
        elif self.auth_mode is AuthMode.STANDALONE:
            if not self.oidc_client_id or not self.oidc_client_secret:
                raise ValueError("auth_mode=standalone needs IHO_OIDC_CLIENT_ID and IHO_OIDC_CLIENT_SECRET.")
            if not self.allowed_domain_set and not self.allowed_email_set:
                raise ValueError("auth_mode=standalone needs IHO_ALLOWED_DOMAINS or IHO_ALLOWED_EMAILS.")
            if self.oidc_provider not in ("google", "oidc"):
                raise ValueError("IHO_OIDC_PROVIDER must be google or oidc.")
        else:
            raise ValueError(f"auth_mode={self.auth_mode} is not implemented yet; use dev or standalone.")
        return self

    @property
    def allowed_domain_set(self) -> set[str]:
        return {d.strip().lower() for d in self.allowed_domains.split(",") if d.strip()}

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def oauth_redirect_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.oauth_redirect_hosts.split(",") if h.strip()}

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
