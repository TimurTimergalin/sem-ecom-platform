from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    yookassa_account_id: str
    yookassa_secret_key: str
    yookassa_return_url: str
    yookassa_api_url: str = "https://api.yookassa.ru/v3"
    yookassa_timeout: int = 1800
    yookassa_max_attempts: int = 3
    yookassa_verify: bool | None = None
