from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:7LcPCBpbZBtQqrv8HT4jJE6q5SK0C7z3OxVQoQnByl0Z9j052Yxgpp5agIjxgtus@213.142.148.57:5432/sevkbul"
    frontend_url: str = ""  # Coolify'da FRONTEND_URL=https://sevkbul.rfqcollector.com

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    class Config:
        env_file = ".env"

    @property
    def all_cors_origins(self) -> list[str]:
        """Frontend URL dahil tüm izinli origin'leri döner."""
        origins = list(self.cors_origins)
        if self.frontend_url:
            url = self.frontend_url.strip().rstrip("/")
            if url and url not in origins:
                origins.append(url)
        return origins


settings = Settings()
