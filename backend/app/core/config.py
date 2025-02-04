from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PIONIX_KEY: str
    PIONIX_USER_AGENT: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
