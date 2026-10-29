from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # iho-server: IHO_TRACKER_* variables. The database is the server's (iho.tracker.service binds it).
    model_config = SettingsConfigDict(env_prefix="IHO_TRACKER_", env_file=None, extra="ignore")

    app_name: str = "InHouseOS tracker"
    app_env: str = "production"
    database_url: str = "sqlite://"
    service_tokens: str = ""
    admin_emails: str = ""
    sla_days: str = "1:1,2:3,3:7"
    local_auth_mock_email: str | None = None
    local_auth_mock_name: str | None = None

    # Links to an action, decision or team view in tool answers. Empty: no links (iho has no tracker UI yet).
    public_base_url: str = ""

    # Adocao do pacote do dia (app/adoption.py): meta e janela em dias uteis; feriados extras (AAAA-MM-DD,...).
    adoption_target: float = 0.8
    adoption_window_days: int = 20
    extra_holidays: str = ""

    # Cadencia de update de projeto (app/project_updates.py): dias uteis antes do prazo em que o
    # dono passa a ser lembrado, por prioridade do projeto (prioridade:dias).
    update_remind_days: str = "1:2,2:1,3:0"

    # Organograma (0.16.0, app/org.py): o escritorio e a fonte, lido com o actor JWT que chega do MCP
    # (sem segredo proprio). Vazio desliga; o cache entao aprende so com os reportes diretos do token.
    office_org_url: str = ""
    org_cache_seconds: int = 900

    @property
    def service_token_set(self) -> set[str]:
        return {t.strip() for t in self.service_tokens.split(",") if t.strip()}

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def sla(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for pair in self.sla_days.split(","):
            if ":" in pair:
                sev, days = pair.split(":", 1)
                out[int(sev)] = int(days)
        return out or {1: 1, 2: 3, 3: 7}

    @property
    def update_remind(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for pair in self.update_remind_days.split(","):
            if ":" in pair:
                prio, days = pair.split(":", 1)
                out[int(prio)] = int(days)
        return out or {1: 2, 2: 1, 3: 0}

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


settings = Settings()
