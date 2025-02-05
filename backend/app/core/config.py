from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # General
    APP_NAME: str = "off-key"

    # Schedule
    PERIODIC_INTERVAL: int = 10

    # Persistence (postgres)
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "admin"
    POSTGRES_DB: str = "offkey_pg"  # noqa
    POSTGRES_PORT: int = 5432
    POSTGRES_HOST: str = (
        "localhost"  # use 'postgres' if connecting from another container
    )

    # External
    PIONIX_KEY: str = ""
    PIONIX_USER_AGENT: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def database_url(self):
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()  # noqa
