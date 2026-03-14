"""Credential Vault — encrypted storage for API keys and OAuth tokens."""
import base64
import logging
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from atlas.contracts.errors import CredentialError
from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)

# Fixed salt for key derivation. In production, you'd store a random salt per-vault,
# but for a single-user local tool this is sufficient.
_SALT = b"atlas-credential-vault-v1"


def _derive_key(passphrase: str) -> bytes:
    """Derive a Fernet key from a passphrase using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


class CredentialVault:
    """Encrypted credential storage backed by SQLite."""

    def __init__(self, db: DatabaseStore, passphrase: str):
        self._db = db
        self._fernet = Fernet(_derive_key(passphrase))

    async def store(
        self,
        service: str,
        key: str,
        value: str,
        expires_at: str | None = None,
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
        logger.info("Stored credential: %s/%s", service, key)

    async def get(self, service: str, key: str) -> str | None:
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

    async def delete(self, service: str, key: str) -> None:
        await self._db.db.execute(
            "DELETE FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        await self._db.db.commit()
        logger.info("Deleted credential: %s/%s", service, key)

    async def list_services(self) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT DISTINCT service FROM credentials ORDER BY service"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_keys(self, service: str) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT key FROM credentials WHERE service=? ORDER BY key",
            (service,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
