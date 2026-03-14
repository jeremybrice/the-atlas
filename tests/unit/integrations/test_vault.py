import pytest
from atlas.integrations.vault import CredentialVault


@pytest.fixture
async def vault(db):
    v = CredentialVault(db=db, passphrase="test-passphrase-for-unit-tests")
    return v


async def test_store_and_get(vault):
    await vault.store("github", "token", "ghp_abc123")
    result = await vault.get("github", "token")
    assert result == "ghp_abc123"


async def test_get_nonexistent_returns_none(vault):
    result = await vault.get("github", "nonexistent")
    assert result is None


async def test_store_overwrites_existing(vault):
    await vault.store("github", "token", "old_value")
    await vault.store("github", "token", "new_value")
    result = await vault.get("github", "token")
    assert result == "new_value"


async def test_delete(vault):
    await vault.store("github", "token", "ghp_abc123")
    await vault.delete("github", "token")
    result = await vault.get("github", "token")
    assert result is None


async def test_list_services(vault):
    await vault.store("github", "token", "ghp_abc")
    await vault.store("slack", "bot_token", "xoxb_abc")
    services = await vault.list_services()
    assert set(services) == {"github", "slack"}


async def test_list_keys_for_service(vault):
    await vault.store("github", "token", "ghp_abc")
    await vault.store("github", "webhook_secret", "whsec_abc")
    keys = await vault.list_keys("github")
    assert set(keys) == {"token", "webhook_secret"}


async def test_values_are_encrypted_in_db(vault, db):
    await vault.store("github", "token", "ghp_abc123")
    cursor = await db.db.execute(
        "SELECT encrypted_value FROM credentials WHERE service='github' AND key='token'"
    )
    row = await cursor.fetchone()
    # The stored value should NOT be the plaintext
    assert row[0] != b"ghp_abc123"
    assert row[0] != "ghp_abc123"


async def test_store_with_expiry(vault):
    await vault.store("github", "oauth", "token_val", expires_at="2026-12-31T00:00:00Z")
    result = await vault.get("github", "oauth")
    assert result == "token_val"
