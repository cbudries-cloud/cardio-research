from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARDIO_", extra="ignore")

    database_url: str = "postgresql+psycopg://cardio:cardio@db:5432/cardio"
    document_root: str = "/data/documents"
    max_upload_bytes: int = 20 * 1024 * 1024

    # Local-only request guard (see docs/safety-boundaries.md).
    # Comma-separated. State-changing requests whose Origin is not listed are refused.
    allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    # Host header allowlist (DNS-rebinding defense). "api" is the compose service name
    # used by the web container's server-side proxy.
    allowed_hosts: str = "127.0.0.1,localhost,api,testserver"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
