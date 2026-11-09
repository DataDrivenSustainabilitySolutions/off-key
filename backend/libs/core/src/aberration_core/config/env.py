from dotenv import find_dotenv, load_dotenv


def load_base_env() -> None:
    """Load base .env file from the project tree."""
    load_dotenv()


def load_dev_env() -> str | None:
    """Load dev.env override if present and return loaded path."""
    dev_env = find_dotenv("dev.env")
    if dev_env:
        load_dotenv(dev_env, override=True)
        return dev_env
    return None


def load_env() -> str | None:
    """Load base env and optional dev override in order."""
    load_base_env()
    return load_dev_env()
