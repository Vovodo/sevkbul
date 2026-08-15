from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./sevkbul.db"
    cors_origins: list[str] = [
        "*",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://*.vercel.app",
        "https://*.onrender.com",
    ]

    class Config:
        env_file = ".env"


settings = Settings()
