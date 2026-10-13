from app.core.security import hash_password, verify_password


def test_password_is_hashed_before_storage() -> None:
    plaintext = "correct horse battery staple"

    hashed = hash_password(plaintext)

    assert hashed != plaintext
    assert hashed.startswith("$argon2")
    assert verify_password(plaintext, hashed) is True
    assert verify_password("wrong password", hashed) is False
