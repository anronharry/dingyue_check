"""
订阅数据存储模块
负责管理订阅链接的持久化存储 (JSON)
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "subscriptions.json")

class SubscriptionStorage:
    def __init__(self):
        self._ensure_data_dir()
        self.subscriptions = self._load_data()
        
    def _ensure_data_dir(self):
        """确保数据目录存在"""
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            
    def _load_data(self):
        """加载数据"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载订阅数据失败: {e}")
                return {}
        return {}
        
    def _save_data(self):
        """保存数据"""
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.subscriptions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存订阅数据失败: {e}")
            
    def add_or_update(self, url, info):
        """
        添加或更新订阅
        
        Args:
            url: 订阅链接
            info: 解析后的订阅信息
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 提取关键信息
        data = {
            'name': info.get('name', '未知订阅'),
            'url': url,
            'updated_at': now,
            'expire_time': info.get('expire_time'),
            'node_count': info.get('node_count', 0),
            'last_check_status': 'success'
        }
        
        # 如果是新订阅，记录添加时间
        if url not in self.subscriptions:
            data['added_at'] = now
        else:
            data['added_at'] = self.subscriptions[url].get('added_at', now)
            
        self.subscriptions[url] = data
        self._save_data()
        logger.info(f"已保存订阅: {data['name']}")
        
    def get_all(self):
        """获取所有订阅"""
        return self.subscriptions
        
    def remove(self, url):
        """删除订阅"""
        if url in self.subscriptions:
            del self.subscriptions[url]
            self._save_data()
            return True
        return False
