"""Credential Vault — encrypted storage for API keys and OAuth tokens."""
import base64
import logging
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from atlas.contracts.errors import CredentialError
from atlas.contracts.types import ExecutionContext
from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a passphrase using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


class CredentialVault:
    """Encrypted credential storage backed by SQLite. Use CredentialVault.create() to construct."""

    def __init__(self, db: DatabaseStore, fernet: Fernet):
        """Internal constructor. Use CredentialVault.create() instead."""
        self._db = db
        self._fernet = fernet

    @classmethod
    async def create(cls, db: DatabaseStore, passphrase: str) -> "CredentialVault":
        """Create a CredentialVault with a per-database random salt."""
        salt = await cls._get_or_create_salt(db)
        fernet = Fernet(_derive_key(passphrase, salt))
        return cls(db=db, fernet=fernet)

    @staticmethod
    def _log_ctx(ctx: ExecutionContext | None) -> str:
        """Format correlation_id for log messages."""
        if ctx:
            return f"[{ctx.correlation_id}] "
        return ""

    @staticmethod
    async def _get_or_create_salt(db: DatabaseStore) -> bytes:
        """Retrieve existing salt from vault_meta, or generate and store a new one."""
        cursor = await db.db.execute(
            "SELECT value FROM vault_meta WHERE key = 'salt'"
        )
        row = await cursor.fetchone()
        if row:
            return row[0]
        salt = os.urandom(32)
        await db.db.execute(
            "INSERT INTO vault_meta (key, value) VALUES ('salt', ?)",
            (salt,),
        )
        await db.db.commit()
        return salt

    async def store(
        self,
        service: str,
        key: str,
        value: str,
        expires_at: str | None = None,
        ctx: ExecutionContext | None = None,
    ) -> None:
        encrypted = self._fernet.encrypt(value.encode())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.db.execute(
            """INSERT INTO credentials (service, key, encrypted_value, expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(service, key) DO UPDATE SET
                encrypted_value=excluded.encrypted_value,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at""",
            (service, key, encrypted, expires_at, now, now),
        )
        await self._db.db.commit()
        logger.info("%sStored credential: %s/%s", self._log_ctx(ctx), service, key)

    async def get(self, service: str, key: str, ctx: ExecutionContext | None = None) -> str | None:
        cursor = await self._db.db.execute(
            "SELECT encrypted_value FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode()
        except InvalidToken as e:
            raise CredentialError(
                f"Decryption failed for {service}/{key}: wrong passphrase or corrupted data",
                cause=e,
            )

    async def delete(self, service: str, key: str, ctx: ExecutionContext | None = None) -> None:
        await self._db.db.execute(
            "DELETE FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        await self._db.db.commit()
        logger.info("%sDeleted credential: %s/%s", self._log_ctx(ctx), service, key)

    async def list_services(self, ctx: ExecutionContext | None = None) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT DISTINCT service FROM credentials ORDER BY service"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_keys(self, service: str, ctx: ExecutionContext | None = None) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT key FROM credentials WHERE service=? ORDER BY key",
            (service,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
