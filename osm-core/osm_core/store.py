"""Backward-compatible re-export of ConversationStore.

Canonical location is osm_core.sms.conversation. This file exists so that
existing code importing from osm_core.store continues to work.
"""

from osm_core.sms.conversation import ConversationStore  # noqa: F401
