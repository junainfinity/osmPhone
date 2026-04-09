"""Conversation Store — Component PY-001.12.

SQLite-backed persistent storage for SMS conversation history.
Stores all messages (incoming + outgoing) per contact, enabling the LLM
to build contextual prompts from prior conversation.

Canonical location: osm_core/sms/conversation.py (per ARCHITECTURE.md spec).
Note: Also importable from osm_core.store for backward compatibility.

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Moved from osm_core/store.py to osm_core/sms/conversation.py per spec
  - osm_core/store.py retained as re-export for backward compatibility
"""

import sqlite3
import os
from typing import List, Dict, Any

class ConversationStore:
    def __init__(self, db_path: str = "conversations.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        # ensure dir exists
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    body TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_contact ON messages (contact)')
            conn.commit()

    def add_message(self, contact: str, direction: str, body: str) -> None:
        if direction not in ("incoming", "outgoing"):
            raise ValueError("direction must be 'incoming' or 'outgoing'")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO messages (contact, direction, body) VALUES (?, ?, ?)',
                (contact, direction, body)
            )
            conn.commit()

    def get_history(self, contact: str, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                'SELECT * FROM messages WHERE contact = ? ORDER BY timestamp ASC LIMIT ?',
                (contact, limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all_threads(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT m1.* FROM messages m1
                INNER JOIN (
                    SELECT MAX(id) as max_id
                    FROM messages
                    GROUP BY contact
                ) m2 ON m1.id = m2.max_id
                ORDER BY m1.timestamp DESC, m1.id DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
