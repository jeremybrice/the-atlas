"""Entity Mapper — bidirectional mapping between ATLAS IDs and external service IDs."""

import json
import logging
from datetime import datetime, timezone

from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


class EntityMapper:
    """Maps external service entities to ATLAS entities and vice versa."""

    def __init__(self, db: DatabaseStore):
        self._db = db

    async def link(
        self,
        service: str,
        external_id: str,
        atlas_type: str,
        atlas_id: str,
        metadata: dict | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.db.execute(
            """INSERT INTO entity_mappings (service, external_id, atlas_type, atlas_id, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(service, external_id) DO UPDATE SET
                atlas_type=excluded.atlas_type,
                atlas_id=excluded.atlas_id,
                metadata=excluded.metadata""",
            (
                service,
                external_id,
                atlas_type,
                atlas_id,
                json.dumps(metadata or {}),
                now,
            ),
        )
        await self._db.db.commit()

    async def get_atlas_id(
        self, service: str, external_id: str
    ) -> tuple[str, str] | None:
        cursor = await self._db.db.execute(
            "SELECT atlas_type, atlas_id FROM entity_mappings WHERE service=? AND external_id=?",
            (service, external_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return (row[0], row[1])

    async def get_external_id(
        self, service: str, atlas_type: str, atlas_id: str
    ) -> str | None:
        cursor = await self._db.db.execute(
            "SELECT external_id FROM entity_mappings WHERE service=? AND atlas_type=? AND atlas_id=?",
            (service, atlas_type, atlas_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

    async def unlink(self, service: str, external_id: str) -> None:
        await self._db.db.execute(
            "DELETE FROM entity_mappings WHERE service=? AND external_id=?",
            (service, external_id),
        )
        await self._db.db.commit()
