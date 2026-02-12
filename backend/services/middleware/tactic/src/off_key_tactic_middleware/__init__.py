"""TACTIC middleware package."""


def main() -> None:
    """
    Lazily resolve and run the service entrypoint.

    Keeping this lazy avoids executing the full application import graph
    when the package itself is imported for non-runtime use (e.g. tests).
    """
    from .main import main as run_main

    run_main()


__all__ = ["main"]
