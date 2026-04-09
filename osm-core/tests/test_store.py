"""
test_store.py - Tests for Conversation Store

This file contains unit tests for the ConversationStore class (PY-001.12),
verifying database initialization, inserting messages, checking histories,
and correctly identifying all active threads and their last responses.
"""

import pytest
import os
import tempfile
import sqlite3
import time
from osm_core.store import ConversationStore

@pytest.fixture
def store():
    # Use a temporary file for the database
    fd, path = tempfile.mkstemp()
    os.close(fd)
    
    _store = ConversationStore(db_path=path)
    yield _store
    
    # Cleanup
    if os.path.exists(path):
        os.remove(path)

def test_store_created_with_schema(store):
    # UT-PY-001.12-01 | Create DB | First call | SQLite file created with schema
    assert os.path.exists(store.db_path)
    with sqlite3.connect(store.db_path) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        assert cursor.fetchone() is not None

def test_add_message(store):
    # UT-PY-001.12-02 | Add message | `add_message("+1234", "incoming", "Hi")` | Row inserted
    store.add_message("+1234", "incoming", "Hi")
    with sqlite3.connect(store.db_path) as conn:
        cursor = conn.execute("SELECT count(*) FROM messages WHERE contact='+1234'")
        assert cursor.fetchone()[0] == 1

def test_add_message_invalid_direction(store):
    with pytest.raises(ValueError):
        store.add_message("+1234", "invalid", "Hi")

def test_get_history(store):
    # UT-PY-001.12-03 | Get history | `get_history("+1234", limit=10)` | List of messages in order
    store.add_message("+1234", "incoming", "Hi")
    store.add_message("+1234", "outgoing", "Hello")
    
    history = store.get_history("+1234", limit=10)
    assert len(history) == 2
    assert history[0]["direction"] == "incoming"
    assert history[0]["body"] == "Hi"
    assert history[1]["direction"] == "outgoing"
    assert history[1]["body"] == "Hello"

def test_get_all_threads(store):
    # UT-PY-001.12-04 | Get all threads | `get_all_threads()` | List with last message per contact
    store.add_message("+1", "incoming", "Hi 1")
    time.sleep(0.01) # Ensure different timestamps
    store.add_message("+1", "outgoing", "Reply 1")
    time.sleep(0.01)
    store.add_message("+2", "incoming", "Hi 2")
    
    threads = store.get_all_threads()
    assert len(threads) == 2
    
    # Ordered by timestamp DESC
    assert threads[0]["contact"] == "+2"
    assert threads[0]["body"] == "Hi 2"
    
    assert threads[1]["contact"] == "+1"
    assert threads[1]["body"] == "Reply 1"

def test_empty_thread(store):
    # UT-PY-001.12-05 | Empty thread | `get_history("+9999")` | Empty list, no error
    history = store.get_history("+9999")
    assert isinstance(history, list)
    assert len(history) == 0
