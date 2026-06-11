from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Auth0
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_client_id: str = ""
    auth0_client_secret: str = ""

    # App
    secret_key: str = "change-me"
    app_base_url: str = "http://localhost:8000"

    # Database
    database_url: str = "sqlite:///./metahound_server.db"

    # SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""


settings = Settings()
