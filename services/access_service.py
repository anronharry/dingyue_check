"""Access control service decoupled from Telegram handlers."""


from __future__ import annotations
from app.constants import NO_PERMISSION_ALERT, NO_PERMISSION_MSG


class AccessService:
    def __init__(self, user_manager, access_state_store, static_allowed_user_ids: set[int] | None = None):
        self.user_manager = user_manager
        self.access_state_store = access_state_store
        self.static_allowed_user_ids = static_allowed_user_ids or set()

    def is_owner_uid(self, uid: int | None) -> bool:
        return bool(uid) and self.user_manager.is_owner(uid)

    def is_authorized_uid(self, uid: int | None) -> bool:
        if not uid:
            return False
        if self.user_manager.is_owner(uid):
            return True
        if self.access_state_store.is_allow_all_users_enabled():
            return True
        return self.user_manager.is_authorized(uid) or uid in self.static_allowed_user_ids

    def is_allow_all_users_enabled(self) -> bool:
        return self.access_state_store.is_allow_all_users_enabled()

    def set_allow_all_users(self, enabled: bool) -> tuple[bool, bool]:
        return self.access_state_store.set_allow_all_users(enabled)

    def get_no_permission_message(self) -> str:
        return NO_PERMISSION_MSG

    def get_no_permission_alert(self) -> str:
        return NO_PERMISSION_ALERT
