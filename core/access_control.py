"""
Access Control Manager
负责持久化管理授权用户名单，并处理四级权限校验。
"""
from __future__ import annotations


import json
import os
import logging
from typing import Set

logger = logging.getLogger(__name__)

class UserManager:
    """管理授权用户名单"""
    
    def __init__(self, db_path: str, owner_id: int):
        self.db_path = db_path
        self.owner_id = owner_id
        self.authorized_users: Set[int] = set()
        self._load()

    def _load(self):
        """从文件加载授权用户"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.authorized_users = set(data)
            except Exception as e:
                logger.error(f"加载授权用户失败: {e}")
        
        # 确保 Owner 始终在授权名单中
        if self.owner_id > 0:
            self.authorized_users.add(self.owner_id)

    def _save(self):
        """保存授权用户到文件"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(list(self.authorized_users), f, indent=2)
        except Exception as e:
            logger.error(f"保存授权用户失败: {e}")

    def add_user(self, user_id: int) -> bool:
        """添加授权用户"""
        if user_id in self.authorized_users:
            return False
        self.authorized_users.add(user_id)
        self._save()
        return True

    def remove_user(self, user_id: int) -> bool:
        """移除授权用户"""
        if user_id == self.owner_id:
            return False # 不能移除 Owner
        if user_id in self.authorized_users:
            self.authorized_users.remove(user_id)
            self._save()
            return True
        return False

    def get_all(self) -> Set[int]:
        """获取所有授权用户"""
        return self.authorized_users

    def is_owner(self, user_id: int) -> bool:
        """检查是否为 Owner"""
        return user_id == self.owner_id and user_id > 0

    def is_authorized(self, user_id: int) -> bool:
        """检查是否为授权用户"""
        # 移除危险的“未配置即开放”回退逻辑，强制依赖白名单与 Owner
        return user_id in self.authorized_users
