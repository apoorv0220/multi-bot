from auth import create_access_token, decode_token, hash_password, verify_password


def test_password_hashing_roundtrip():
    password = "StrongPass123!"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)


def test_access_token_contains_role_and_tenant():
    token = create_access_token("user-id", "admin", "tenant-id")
    payload = decode_token(token)
    assert payload["sub"] == "user-id"
    assert payload["role"] == "admin"
    assert payload["tenant_id"] == "tenant-id"
