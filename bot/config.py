from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "books_store"
    db_user: str = "books"
    db_password: str = "books"

    # How many of the closest stores to offer the user.
    nearest_limit: int = 5

    # Comma-separated Telegram chat IDs allowed into the admin panel.
    admin_ids: str = "1671347908"

    # Google Sheet to import real stores from (public "Anyone with link").
    sheet_id: str = "1x8zH8C4aFXsUbqh0cAqIJaN0O0Sv5q5wdVXk-zEHOVc"
    sheet_gid: str = "0"

    # Timezone offset (hours from UTC) for interpreting scheduled-post times.
    # Tashkent = +5 (no DST). The container clock is UTC.
    schedule_tz_offset: int = 5

    # Webhook mode: set WEBHOOK_URL to the public base URL (e.g.
    # https://falaqnashrcloud.uz) to run via webhook instead of long polling.
    # Empty -> polling mode (good for local dev).
    webhook_url: str = ""
    webhook_path: str = "/webhook"
    webhook_secret: str = ""  # optional; derived from the token if left empty
    web_port: int = 8080  # internal port the webhook server listens on

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_url.strip())

    @property
    def full_webhook_url(self) -> str:
        return f"{self.webhook_url.rstrip('/')}{self.webhook_path}"

    @property
    def resolved_secret(self) -> str:
        """Secret token Telegram echoes back so we can verify requests."""
        if self.webhook_secret:
            return self.webhook_secret
        import hashlib

        return hashlib.sha256(self.bot_token.encode()).hexdigest()[:40]

    @property
    def admin_id_set(self) -> set[int]:
        ids: set[int] = set()
        for part in self.admin_ids.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
        return ids

    @property
    def sheet_csv_url(self) -> str:
        return (
            f"https://docs.google.com/spreadsheets/d/{self.sheet_id}"
            f"/export?format=csv&gid={self.sheet_gid}"
        )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
