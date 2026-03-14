async def test_credentials_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='credentials'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "credentials"


async def test_credentials_columns(db):
    cursor = await db.db.execute("PRAGMA table_info(credentials)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "service" in columns
    assert "key" in columns
    assert "encrypted_value" in columns
    assert "expires_at" in columns
    assert "created_at" in columns
