"""
Workspace Manager
统一调度基于 data/ 目录的生命周期与IO操作。
聚合了 Jiedian 的 raw / yaml / txt / temp / archives 管理机制，并与 dingyue_TG 的 storage 相关联。
"""
from __future__ import annotations


import os
import shutil
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class WorkspaceManager:
    """管理全局数据目录与缓存清理"""

    def __init__(self, base_dir: str = "data"):
        self.base_dir = base_dir
        self.db_dir = os.path.join(base_dir, "db")
        self.raw_dir = os.path.join(base_dir, "raw")
        self.yaml_dir = os.path.join(base_dir, "yaml_workspace")
        self.txt_dir = os.path.join(base_dir, "txt_workspace")
        self.temp_dir = os.path.join(base_dir, "temp")
        self.archives_dir = os.path.join(base_dir, "archives")

        self._init_directories()

    def _init_directories(self):
        """初始化全部工作子目录"""
        dirs = [
            self.db_dir, self.raw_dir, self.yaml_dir, 
            self.txt_dir, self.temp_dir, self.archives_dir
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
            
    def get_subscription_db_path(self) -> str:
        """获取结构化订阅 JSON 保存路径"""
        return os.path.join(self.db_dir, "subscriptions.json")

    def save_raw_file(self, filename: str, content: bytes) -> str:
        """保存用户上传的原始文件 (带安全性清洗)"""
        # 核心加固：强制清洗文件名防止路径穿越
        safe_filename = os.path.basename(filename)
        filepath = os.path.join(self.raw_dir, safe_filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        return filepath

    def get_temp_file(self, prefix: str = "tmp_", suffix: str = ".yaml") -> str:
        """获取一个临时测速文件的安全路径"""
        timestamp = int(time.time() * 1000)
        filename = f"{prefix}{timestamp}{suffix}"
        return os.path.join(self.temp_dir, filename)

    def archive_file(self, source_path: str, reason: str = "expired") -> str:
        """将文件移入归档区"""
        if not os.path.exists(source_path):
            return ""
            
        filename = os.path.basename(source_path)
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived_name = f"{reason}_{date_str}_{filename}"
        dest_path = os.path.join(self.archives_dir, archived_name)
        
        try:
            shutil.move(source_path, dest_path)
            logger.info(f"文件已归档: {dest_path}")
            return dest_path
        except Exception as e:
            logger.error(f"归档文件失败 {source_path}: {e}")
            return ""

    def cleanup_temp(self, max_age_hours: int = 24) -> int:
        """清理过期的临时文件"""
        count = 0
        now = time.time()
        for filename in os.listdir(self.temp_dir):
            filepath = os.path.join(self.temp_dir, filename)
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > max_age_hours * 3600:
                    try:
                        os.remove(filepath)
                        count += 1
                    except Exception as e:
                        logger.error(f"清理临时文件失败 {filepath}: {e}")
        
        if count > 0:
            logger.info(f"已清理 {count} 个过期临时测速文件")
        return count
