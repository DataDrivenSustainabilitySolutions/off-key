from pydantic_settings import BaseSettings
from dotenv import find_dotenv, load_dotenv

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)

class Settings(BaseSettings):

    APP_NAME: str

    JWT_SECRET: str
    JWT_VERIFICATION_SECRET: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: str

    EMAIL_USERNAME: str
    EMAIL_PASSWORD: str
    EMAIL_FROM: str
    FRONTEND_BASE_URL: str
    SMTP_SERVER: str
    SMTP_PORT: int
    MAIL_STARTTLS: bool
    MAIL_SSL_TLS: bool

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: str
    POSTGRES_HOST: str  # 'postgres' if connecting from another container

    PIONIX_KEY: str
    PIONIX_USER_AGENT: str

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
