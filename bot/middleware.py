from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import BaseHandler

logger = logging.getLogger("iagent.middleware")


def is_allowed(update: Update, allowed_ids: list[int]) -> bool:
    """Return True if the sender is in the allowlist, or if the allowlist is empty (open mode)."""
    if not allowed_ids:
        return True
    user = update.effective_user
    if user is None:
        return False
    return user.id in allowed_ids


class AllowlistFilter:
    """Callable filter for ConversationHandler / MessageHandler."""
    def __init__(self, allowed_ids: list[int]) -> None:
        self._allowed: set[int] = set(allowed_ids)

    def __call__(self, update: Optional[Update]) -> bool:
        if update is None:
            return False
        if not self._allowed:
            return True
        user = update.effective_user
        return user is not None and user.id in self._allowed
