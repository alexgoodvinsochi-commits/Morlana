from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str = ""
    DATABASE_URL: str = "postgresql+psycopg://user:pass@localhost:5432/morlana_db"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    PAYMENT_PROVIDER_TOKEN: str = ""
    CORS_ORIGINS: str = "http://localhost:3000"
    LLM_FREE_MODEL: str = "mimo-v2-flash"
    LLM_PREMIUM_MODEL: str = "mimo-v2-flash"
    SKIP_ONBOARDING: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
