from off_key_api_gateway.services.auth import get_password_hash, verify_password


def test_bcrypt_password_hash_round_trip() -> None:
    password = "correct horse battery staple"

    hashed_password = get_password_hash(password)

    assert hashed_password != password
    assert verify_password(password, hashed_password)
    assert not verify_password("wrong password", hashed_password)


def test_password_verification_rejects_malformed_hash() -> None:
    assert not verify_password("password", "not-a-bcrypt-hash")
