from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://sevkiyat:sevkiyat123@localhost:5432/sevkiyat_db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    class Config:
        env_file = ".env"


settings = Settings()
