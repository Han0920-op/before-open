import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str | None = field(default=None, repr=False)
    cookie_secure: bool = True
    allowed_origins: tuple[str, ...] = ()
    body_limit: int = 262144
    body_timeout: float = 10.0
    rate_limit: int = 120
    session_days: int = 30

    def __post_init__(self) -> None:
        if "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS must contain explicit origins")
        if min(self.body_limit, self.rate_limit, self.session_days) < 1 or self.body_timeout <= 0:
            raise ValueError("runtime limits must be positive")

    @classmethod
    def load(cls) -> "Settings":
        local_url = Path(__file__).resolve().parents[3] / ".local" / "database-url"
        url = os.environ.get("DATABASE_URL")
        local = url is None and local_url.exists()
        if local:
            url = local_url.read_text().strip()
        secure_setting = os.environ.get("COOKIE_SECURE", "false" if local else "true").lower()
        if secure_setting not in {"true", "false"}:
            raise ValueError("COOKIE_SECURE must be true or false")
        return cls(
            database_url=url,
            cookie_secure=secure_setting == "true",
            allowed_origins=tuple(
                o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
            ),
        )
