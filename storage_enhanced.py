"""
增强的订阅数据存储模块
支持标签管理、导出导入功能
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "subscriptions.json")


class SubscriptionStorage:
    """增强的订阅存储类（支持标签和导出导入）"""

    def __init__(self, data_file: str = DATA_FILE):
        """
        初始化存储

        Args:
            data_file: 数据文件路径
        """
        self.data_file = data_file
        self._ensure_data_dir()
        self.subscriptions: Dict[str, Dict[str, Any]] = self._load_data()
        self._batch_depth = 0
        self._dirty = False

    def _ensure_data_dir(self):
        """确保数据目录存在"""
        data_dir = os.path.dirname(self.data_file)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logger.info(f"创建数据目录: {data_dir}")

    def _load_data(self) -> Dict[str, Dict[str, Any]]:
        """
        加载数据

        Returns:
            订阅数据字典
        """
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"加载了 {len(data)} 个订阅")
                    return data
            except Exception as e:
                logger.error(f"加载订阅数据失败: {e}")
                return {}
        return {}

    def _save_data(self):
        """保存数据到文件"""
        try:
            # 使用临时文件 + 原子重命名，避免写入中断导致数据丢失
            temp_file = self.data_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.subscriptions, f, indent=2, ensure_ascii=False)

            os.replace(temp_file, self.data_file)
            logger.debug(f"保存了 {len(self.subscriptions)} 个订阅")
        except Exception as e:
            logger.error(f"保存订阅数据失败: {e}")

    def _mark_dirty(self):
        """标记数据已变更，在非批处理模式下立即落盘。"""
        self._dirty = True
        if self._batch_depth == 0:
            self._save_data()
            self._dirty = False

    def begin_batch(self):
        """开始批处理，延迟磁盘写入。"""
        self._batch_depth += 1

    def end_batch(self, save: bool = True):
        """结束批处理，可选触发一次落盘。"""
        if self._batch_depth > 0:
            self._batch_depth -= 1
        if save and self._batch_depth == 0 and self._dirty:
            self._save_data()
            self._dirty = False

    def add_or_update(self, url: str, info: Dict[str, Any]):
        """
        添加或更新订阅

        Args:
            url: 订阅链接
            info: 解析后的订阅信息
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        data = {
            'name': info.get('name', '未知订阅'),
            'url': url,
            'updated_at': now,
            'expire_time': info.get('expire_time'),
            'node_count': info.get('node_count', 0),
            'total': info.get('total', 0),
            'used': info.get('used', 0),
            'remaining': info.get('remaining', 0),
            'last_check_status': 'success',
            'tags': []
        }

        if url not in self.subscriptions:
            data['added_at'] = now
            data['tags'] = []
        else:
            data['added_at'] = self.subscriptions[url].get('added_at', now)
            data['tags'] = self.subscriptions[url].get('tags', [])

        self.subscriptions[url] = data
        self._mark_dirty()
        logger.info(f"已保存订阅: {data['name']}")

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """获取所有订阅"""
        return self.subscriptions

    def get_by_tag(self, tag: str) -> Dict[str, Dict[str, Any]]:
        """按标签获取订阅"""
        return {
            url: data
            for url, data in self.subscriptions.items()
            if tag in data.get('tags', [])
        }

    def add_tag(self, url: str, tag: str) -> bool:
        """为订阅添加标签"""
        if url not in self.subscriptions:
            logger.warning(f"订阅不存在: {url}")
            return False

        tags = self.subscriptions[url].get('tags', [])
        if tag not in tags:
            tags.append(tag)
            self.subscriptions[url]['tags'] = tags
            self._mark_dirty()
            logger.info(f"为订阅 {self.subscriptions[url]['name']} 添加标签: {tag}")
            return True

        logger.info(f"标签已存在: {tag}")
        return False

    def remove_tag(self, url: str, tag: str) -> bool:
        """移除订阅的标签"""
        if url not in self.subscriptions:
            return False

        tags = self.subscriptions[url].get('tags', [])
        if tag in tags:
            tags.remove(tag)
            self.subscriptions[url]['tags'] = tags
            self._mark_dirty()
            logger.info(f"移除标签: {tag}")
            return True

        return False

    def get_all_tags(self) -> List[str]:
        """获取所有使用过的标签"""
        all_tags = set()
        for data in self.subscriptions.values():
            all_tags.update(data.get('tags', []))
        return sorted(list(all_tags))

    def remove(self, url: str) -> bool:
        """删除订阅"""
        if url in self.subscriptions:
            name = self.subscriptions[url].get('name', 'Unknown')
            del self.subscriptions[url]
            self._mark_dirty()
            logger.info(f"已删除订阅: {name}")
            return True
        return False

    def export_to_file(self, filepath: str) -> bool:
        """导出所有订阅到文件"""
        try:
            export_data = {
                'version': '1.0',
                'exported_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'count': len(self.subscriptions),
                'subscriptions': self.subscriptions
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            logger.info(f"导出 {len(self.subscriptions)} 个订阅到: {filepath}")
            return True
        except Exception as e:
            logger.error(f"导出失败: {e}")
            return False

    def import_from_file(self, filepath: str, merge: bool = True) -> int:
        """从文件导入订阅"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                import_data = json.load(f)

            if 'subscriptions' not in import_data:
                logger.error("导入文件格式错误：缺少 'subscriptions' 字段")
                return 0

            imported_subs = import_data['subscriptions']

            if not merge:
                self.subscriptions = {}

            count = 0
            for url, data in imported_subs.items():
                self.subscriptions[url] = data
                count += 1

            self._mark_dirty()
            logger.info(f"成功导入 {count} 个订阅")
            return count

        except Exception as e:
            logger.error(f"导入失败: {e}")
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self.subscriptions)
        expired = 0
        total_traffic = 0
        total_remaining = 0

        now = datetime.now()

        for data in self.subscriptions.values():
            expire_time_str = data.get('expire_time')
            if expire_time_str:
                try:
                    expire_date = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')
                    if expire_date < now:
                        expired += 1
                except Exception:
                    pass

            total_traffic += data.get('total', 0)
            total_remaining += data.get('remaining', 0)

        return {
            'total': total,
            'expired': expired,
            'active': total - expired,
            'total_traffic': total_traffic,
            'total_remaining': total_remaining,
            'tags': self.get_all_tags()
        }
