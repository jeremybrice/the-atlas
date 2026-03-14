import pytest
from atlas.contracts.errors import CredentialError
from atlas.contracts.types import ExecutionContext
from atlas.integrations.vault import CredentialVault


@pytest.fixture
async def vault(db):
    v = await CredentialVault.create(db=db, passphrase="test-passphrase-for-unit-tests")
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


async def test_get_with_wrong_passphrase_raises_credential_error(db):
    vault1 = await CredentialVault.create(db=db, passphrase="correct-pass")
    await vault1.store("github", "token", "secret123")

    vault2 = await CredentialVault.create(db=db, passphrase="wrong-pass")
    with pytest.raises(CredentialError, match="Decryption failed"):
        await vault2.get("github", "token")


async def test_store_and_get_accepts_execution_context(db):
    vault = await CredentialVault.create(db=db, passphrase="test-passphrase")
    ctx = ExecutionContext.new(mission_id="test-mission")
    await vault.store("github", "token", "ghp_abc123", ctx=ctx)
    result = await vault.get("github", "token", ctx=ctx)
    assert result == "ghp_abc123"


async def test_delete_accepts_execution_context(db):
    vault = await CredentialVault.create(db=db, passphrase="test-passphrase")
    ctx = ExecutionContext.new(mission_id="test-mission")
    await vault.store("github", "token", "ghp_abc123", ctx=ctx)
    await vault.delete("github", "token", ctx=ctx)
    result = await vault.get("github", "token", ctx=ctx)
    assert result is None


async def test_list_services_accepts_execution_context(db):
    vault = await CredentialVault.create(db=db, passphrase="test-passphrase")
    ctx = ExecutionContext.new(mission_id="test-mission")
    await vault.store("github", "token", "ghp_abc", ctx=ctx)
    services = await vault.list_services(ctx=ctx)
    assert "github" in services


async def test_list_keys_accepts_execution_context(db):
    vault = await CredentialVault.create(db=db, passphrase="test-passphrase")
    ctx = ExecutionContext.new(mission_id="test-mission")
    await vault.store("github", "token", "ghp_abc", ctx=ctx)
    keys = await vault.list_keys("github", ctx=ctx)
    assert "token" in keys


async def test_store_logs_correlation_id(db, caplog):
    """When ctx is provided, correlation_id should appear in log output."""
    import logging
    vault = await CredentialVault.create(db=db, passphrase="test-pass")
    ctx = ExecutionContext.new(mission_id="test-mission")
    with caplog.at_level(logging.INFO, logger="atlas.integrations.vault"):
        await vault.store("github", "token", "secret", ctx=ctx)
    assert ctx.correlation_id in caplog.text


async def test_different_vaults_use_different_salts(tmp_path):
    """Two separate vault databases with the same passphrase should use different salts."""
    from atlas.memory.store import DatabaseStore

    db1 = DatabaseStore(str(tmp_path / "vault1.db"))
    await db1.initialize()
    db2 = DatabaseStore(str(tmp_path / "vault2.db"))
    await db2.initialize()

    try:
        v1 = await CredentialVault.create(db=db1, passphrase="same-pass")
        v2 = await CredentialVault.create(db=db2, passphrase="same-pass")
        await v1.store("svc", "key", "secret")
        await v2.store("svc", "key", "secret")

        c1 = await db1.db.execute("SELECT encrypted_value FROM credentials WHERE service='svc'")
        c2 = await db2.db.execute("SELECT encrypted_value FROM credentials WHERE service='svc'")
        row1 = await c1.fetchone()
        row2 = await c2.fetchone()
        assert row1[0] != row2[0]
    finally:
        await db1.close()
        await db2.close()
