"""
Local Metadata Cache and Audit Storage Module (SQLite).
Explicitly designed as a local cache/audit log, NOT an authoritative verification source.
Per PRD Correction 4: Blockchain verification must NEVER fall back to trusting this cache.
"""

from dataclasses import dataclass
import datetime
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pipeline.storage.cache")


@dataclass
class CachedRecord:
    """Represents a record stored in the local SQLite metadata cache."""
    record_id: int
    tx_hash: str
    content_hash: str
    immutable_data: Dict[str, Any]
    audit_metadata: Dict[str, Any]
    created_at: str


class MetadataCache:
    """
    Local SQLite cache for recorded transactions and run metadata.
    Provides offline inspection, field diffing, and duplicate pre-checks.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("CACHE_DB_PATH", "./cache.db")
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Creates table schema if not already present."""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    record_id INTEGER PRIMARY KEY,
                    tx_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    immutable_data TEXT NOT NULL,
                    audit_metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_content_hash ON records(content_hash)
            """)

    def save_record(
        self,
        record_id: int,
        tx_hash: str,
        content_hash: str,
        immutable_data: Dict[str, Any],
        audit_metadata: Dict[str, Any],
    ) -> CachedRecord:
        """Saves a confirmed on-chain record into the local cache."""
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        imm_str = json.dumps(immutable_data, sort_keys=True)
        audit_str = json.dumps(audit_metadata, sort_keys=True)

        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO records 
                (record_id, tx_hash, content_hash, immutable_data, audit_metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (record_id, tx_hash, content_hash, imm_str, audit_str, now_iso),
            )

        logger.info(f"Saved record #{record_id} ({content_hash[:12]}...) to local cache.")
        return CachedRecord(
            record_id=record_id,
            tx_hash=tx_hash,
            content_hash=content_hash,
            immutable_data=immutable_data,
            audit_metadata=audit_metadata,
            created_at=now_iso,
        )

    def get_record(self, record_id: int) -> Optional[CachedRecord]:
        """Retrieves cached record by recordId."""
        row = self._conn.execute(
            "SELECT * FROM records WHERE record_id = ?",
            (record_id,),
        ).fetchone()

        if not row:
            return None

        return CachedRecord(
            record_id=row["record_id"],
            tx_hash=row["tx_hash"],
            content_hash=row["content_hash"],
            immutable_data=json.loads(row["immutable_data"]),
            audit_metadata=json.loads(row["audit_metadata"]),
            created_at=row["created_at"],
        )

    def find_by_content_hash(self, content_hash: str) -> List[CachedRecord]:
        """Finds any existing records that match the given content hash."""
        rows = self._conn.execute(
            "SELECT * FROM records WHERE content_hash = ? ORDER BY record_id ASC",
            (content_hash,),
        ).fetchall()

        return [
            CachedRecord(
                record_id=r["record_id"],
                tx_hash=r["tx_hash"],
                content_hash=r["content_hash"],
                immutable_data=json.loads(r["immutable_data"]),
                audit_metadata=json.loads(r["audit_metadata"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def list_records(self, limit: int = 50) -> List[CachedRecord]:
        """Lists recent records from cache."""
        rows = self._conn.execute(
            "SELECT * FROM records ORDER BY record_id DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [
            CachedRecord(
                record_id=r["record_id"],
                tx_hash=r["tx_hash"],
                content_hash=r["content_hash"],
                immutable_data=json.loads(r["immutable_data"]),
                audit_metadata=json.loads(r["audit_metadata"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
