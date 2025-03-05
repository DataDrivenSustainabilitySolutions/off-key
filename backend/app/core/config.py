from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    APP_NAME: str

    JWT_SECRET: str
    JWT_VERIFICATION_SECRET: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    EMAIL_USERNAME: str
    EMAIL_PASSWORD: str
    EMAIL_FROM: str
    SMTP_SERVER: str
    SMTP_PORT: int
    ADMIN_EMAIL: str
    ADMIN_PASSWORD: str
    MAIL_STARTTLS: bool
    MAIL_SSL_TLS: bool

    PERIODIC_INTERVAL: int

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: str
    POSTGRES_HOST: str  # 'postgres' if connecting from another container

    PIONIX_KEY: str
    PIONIX_USER_AGENT: str

    model_config = SettingsConfigDict(
        env_file="./../../.env", env_file_encoding="utf-8"
    )

    @property
    def database_url(self):
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def async_database_url(self):
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()  # noqa
