from pathlib import Path


def test_data_services_router_is_transport_only():
    """The data API router must not directly access persistence details."""
    router_file = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "middleware"
        / "tactic"
        / "src"
        / "off_key_tactic_middleware"
        / "api"
        / "v1"
        / "data_services.py"
    )
    contents = router_file.read_text(encoding="utf-8")

    forbidden_tokens = [
        "from sqlalchemy",
        "AsyncSession",
        "get_db_async",
        "select(",
        ".execute(",
        ".commit(",
        ".add(",
    ]

    for token in forbidden_tokens:
        assert token not in contents, f"data_services.py must not contain '{token}'"
