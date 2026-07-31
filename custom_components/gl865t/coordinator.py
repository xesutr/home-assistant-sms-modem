from __future__ import annotations
import os
import sqlite3
import hashlib
import logging
from datetime import timedelta, datetime
from logging import Logger
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DEFAULT_NAME
from .modem import GL865TModem

_LOGGER = logging.getLogger(__name__)


class GL865TCoordinator(DataUpdateCoordinator):
    """Data Update Coordinator for Telit GL865 GSM Module with SQLite backend."""

    def __init__(
        self,
        hass: HomeAssistant,
        modem: GL865TModem,
        update_interval: int,
        logger: Logger,
        unique_id: str,
    ) -> None:
        self.modem = modem
        self.unique_id = unique_id

        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            manufacturer="Telit",
            model="GL865T-DUAL",
            name=DEFAULT_NAME,
        )

        self._last_update_time: datetime | None = None
        self._sms_hashes: set[str] = set()
        self.new_sms: list[dict] = []
        self.last_sms: dict | None = None
        
        # Buffer for multipart SMS & full message list
        self._sms_buffer: dict[str, dict] = {}
        self.sms_history: list[dict] = []

        # Database Path: modem.db under integration directory
        db_folder = os.path.dirname(__file__)
        self.db_path = os.path.join(db_folder, "modem.db")
        
        # Auto-create table if not exists on startup
        self._init_db()

        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    # ==================== SQLITE OPERATIONS ====================

    def _init_db(self) -> None:
        """Synchronous method to prepare SQLite database file and table."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sms_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        body TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(sender, timestamp, body)
                    )
                """)
                conn.commit()
        except Exception as e:
            _LOGGER.error("GL865T: SQLite initialization error: %s", e)

    def _sync_load_sms_from_db(self) -> list[dict]:
        """Fetch all SMS records from database ordered from newest to oldest including ID."""
        history: list[dict] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT id, sender, timestamp, body FROM sms_history ORDER BY id DESC")
                rows = cursor.fetchall()
                for row in rows:
                    history.append({
                        "id": row["id"],
                        "sender": row["sender"],
                        "timestamp": row["timestamp"],
                        "body": row["body"],
                    })
        except Exception as e:
            _LOGGER.error("GL865T: SQLite data read error: %s", e)
        return history

    def _sync_insert_sms_to_db(self, messages: list[dict]) -> None:
        """Insert incoming SMS entries into SQLite table and strictly populate generated ID back to dict."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for msg in messages:
                    cursor.execute(
                        "INSERT OR IGNORE INTO sms_history (sender, timestamp, body) VALUES (?, ?, ?)",
                        (msg["sender"], msg["timestamp"], msg["body"]),
                    )
                    if cursor.lastrowid:
                        msg["id"] = cursor.lastrowid
                    else:
                        # Fetch generated ID if OR IGNORE matched existing record
                        cursor.execute(
                            "SELECT id FROM sms_history WHERE sender = ? AND timestamp = ? AND body = ?",
                            (msg["sender"], msg["timestamp"], msg["body"]),
                        )
                        row = cursor.fetchone()
                        if row:
                            msg["id"] = row[0]
                conn.commit()
        except Exception as e:
            _LOGGER.error("GL865T: SQLite save error: %s", e)

    def _sync_delete_sms_from_db(self, sender: str, timestamp: str) -> None:
        """Delete selected SMS from SQLite table using sender and timestamp."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM sms_history WHERE sender = ? AND timestamp = ?",
                    (sender, timestamp),
                )
                conn.commit()
        except Exception as e:
            _LOGGER.error("GL865T: SQLite deletion error: %s", e)

    def _sync_delete_sms_by_id_from_db(self, sms_id: int) -> None:
        """Delete selected SMS from SQLite table using primary key ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sms_history WHERE id = ?", (sms_id,))
                conn.commit()
        except Exception as e:
            _LOGGER.error("GL865T: SQLite ID deletion error: %s", e)

    # ==================== COORDINATOR FLOW ====================

    async def _async_setup(self) -> None:
        """Load history from modem.db into RAM on initial setup."""
        self.sms_history = await self.hass.async_add_executor_job(self._sync_load_sms_from_db)
        for msg in self.sms_history:
            self._sms_hashes.add(self._hash_item(msg))
        if self.sms_history:
            self.last_sms = self.sms_history[0]

    async def _async_update_data(self) -> dict:
        """Fetch data from modem periodically."""
        await self._update_new_sms()
        self._last_update_time = datetime.now()

        return {
            "last_sms": self.last_sms,
            "new_sms_count": len(self.new_sms),
            "sms_history": self.sms_history,
        }

    async def _update_new_sms(self) -> None:
        """Read unread SMS messages, assemble multipart messages, update history, write to DB, and clear SIM."""
        sms_list = await self.hass.async_add_executor_job(self.modem.read_unread_sms)

        if not sms_list:
            self.new_sms = []
            return

        processed_messages: list[dict] = []

        for sms in sms_list:
            sender = sms.get("sender", "Unknown")
            ref_id = sms.get("ref_id")
            total_parts = sms.get("total_parts", 1)
            part_num = sms.get("part_num", 1)
            body = sms.get("body", "")
            timestamp = sms.get("timestamp", "")
            sender_str = sender if sender else "Unknown"

            # Single part SMS
            if total_parts == 1 or ref_id is None:
                processed_messages.append({
                    "sender": sender_str,
                    "timestamp": timestamp,
                    "body": body,
                })
                continue

            # Multipart SMS Buffer
            buffer_key = f"{sender}_{ref_id}"
            if buffer_key not in self._sms_buffer:
                self._sms_buffer[buffer_key] = {
                    "parts": {},
                    "total_parts": total_parts,
                    "sender": sender_str,
                    "timestamp": timestamp,
                }

            self._sms_buffer[buffer_key]["parts"][part_num] = body

            if len(self._sms_buffer[buffer_key]["parts"]) == total_parts:
                parts_dict = self._sms_buffer[buffer_key]["parts"]
                full_body = "".join([parts_dict[p] for p in sorted(parts_dict.keys())])
                buf_ts = self._sms_buffer[buffer_key]["timestamp"]

                processed_messages.append({
                    "sender": sender_str,
                    "timestamp": buf_ts,
                    "body": full_body,
                })
                del self._sms_buffer[buffer_key]

        if processed_messages:
            new_records_to_save: list[dict] = []
            for msg in processed_messages:
                h = self._hash_item(msg)
                if h not in self._sms_hashes:
                    self._sms_hashes.add(h)
                    self.new_sms.append(msg)
                    self.last_sms = msg
                    new_records_to_save.append(msg)
            
            # Save into SQLite database if new records exist and ensure IDs are assigned
            if new_records_to_save:
                await self.hass.async_add_executor_job(self._sync_insert_sms_to_db, new_records_to_save)
                
                # Insert records containing newly assigned ID into RAM list
                for msg in reversed(new_records_to_save):
                    self.sms_history.insert(0, msg)

                # Clear SIM card memory after successful storage
                await self.hass.async_add_executor_job(self.modem.delete_all_read_sms)

    def delete_sms_by_id(self, sms_id: int) -> None:
        """Delete selected SMS by ID from both SQLite database and RAM."""
        try:
            target_id = int(sms_id)
        except (ValueError, TypeError):
            _LOGGER.error("GL865T: Invalid SMS ID format for deletion: %s", sms_id)
            return

        self.hass.async_add_executor_job(self._sync_delete_sms_by_id_from_db, target_id)

        # RAM'den silerken ID hatası ihtimalini sıfırlayan katı filtreleme
        self.sms_history = [
            sms for sms in self.sms_history
            if str(sms.get("id")) != str(target_id)
        ]
        
        self._sms_hashes = {self._hash_item(msg) for msg in self.sms_history}
        if self.sms_history:
            self.last_sms = self.sms_history[0]
        else:
            self.last_sms = None

        self.async_update_listeners()

    def delete_sms(self, sender: str, timestamp: str) -> None:
        """Delete selected SMS from both SQLite (modem.db) database and RAM (Fallback method)."""
        # 1. Delete from SQLite
        self.hass.async_add_executor_job(self._sync_delete_sms_from_db, sender, timestamp)

        # 2. Update RAM state
        self.sms_history = [
            sms for sms in self.sms_history
            if not (str(sms.get("sender")) == str(sender) and str(sms.get("timestamp")) == str(timestamp))
        ]
        
        self._sms_hashes = {self._hash_item(msg) for msg in self.sms_history}
        if self.sms_history:
            self.last_sms = self.sms_history[0]
        else:
            self.last_sms = None

        self.async_update_listeners()

    @staticmethod
    def _hash_item(sms: dict) -> str:
        """Generate unique SHA-1 hash for SMS deduplication."""
        sender = sms.get("sender", "")
        body = sms.get("body", "")
        received_at = sms.get("timestamp", "")
        key = f"{sender}|{body}|{received_at}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()
