from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "realestate"
    db_user: str = "postgres"
    db_password: str = ""
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:8080"]
    site_name: str = "Статистика рынка недвижимости"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
