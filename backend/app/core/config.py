from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    APP_NAME: str
    PERIODIC_INTERVAL: int
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "admin"
    POSTGRES_DB: str = "offkey_pg"  # noqa
    POSTGRES_PORT: int = 5432
    POSTGRES_HOST: str = "localhost"  # 'postgres' if connecting from another container
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


settings = Settings()  # noqa
