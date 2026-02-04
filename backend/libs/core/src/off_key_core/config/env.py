from dotenv import find_dotenv, load_dotenv


def load_base_env() -> None:
    """Load the default .env from the project tree."""
    load_dotenv()


def load_dev_env() -> str | None:
    """Load dev.env overrides if present and return the path used."""
    dev_env = find_dotenv("dev.env")
    if dev_env:
        load_dotenv(dev_env, override=True)
        return dev_env
    return None


def load_env() -> None:
    """Load base and dev environment files in order."""
    load_base_env()
    load_dev_env()
