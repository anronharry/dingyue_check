"""
单元测试 - 存储模块
"""

import pytest
import os
import json
import tempfile
from datetime import datetime
from storage_enhanced import SubscriptionStorage


@pytest.fixture
def temp_storage():
    """创建临时存储实例"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        temp_file = f.name
    
    storage = SubscriptionStorage(data_file=temp_file)
    yield storage
    
    # 清理
    if os.path.exists(temp_file):
        os.remove(temp_file)


class TestSubscriptionStorage:
    """存储功能测试"""
    
    def test_add_subscription(self, temp_storage):
        """测试添加订阅"""
        url = "https://example.com/subscribe"
        info = {
            'name': '测试订阅',
            'node_count': 10,
            'total': 1024**3,
            'used': 512**3,
            'remaining': 512**3
        }
        
        temp_storage.add_or_update(url, info)
        
        all_subs = temp_storage.get_all()
        assert url in all_subs
        assert all_subs[url]['name'] == '测试订阅'
        assert all_subs[url]['node_count'] == 10
    
    def test_update_subscription(self, temp_storage):
        """测试更新订阅"""
        url = "https://example.com/subscribe"
        
        # 第一次添加
        info1 = {'name': '订阅1', 'node_count': 5}
        temp_storage.add_or_update(url, info1)
        
        # 更新
        info2 = {'name': '订阅1-更新', 'node_count': 10}
        temp_storage.add_or_update(url, info2)
        
        all_subs = temp_storage.get_all()
        assert all_subs[url]['name'] == '订阅1-更新'
        assert all_subs[url]['node_count'] == 10
    
    def test_remove_subscription(self, temp_storage):
        """测试删除订阅"""
        url = "https://example.com/subscribe"
        info = {'name': '测试订阅'}
        
        temp_storage.add_or_update(url, info)
        assert url in temp_storage.get_all()
        
        result = temp_storage.remove(url)
        assert result is True
        assert url not in temp_storage.get_all()
    
    def test_add_tag(self, temp_storage):
        """测试添加标签"""
        url = "https://example.com/subscribe"
        info = {'name': '测试订阅'}
        
        temp_storage.add_or_update(url, info)
        temp_storage.add_tag(url, '主力')
        
        all_subs = temp_storage.get_all()
        assert '主力' in all_subs[url]['tags']
    
    def test_get_by_tag(self, temp_storage):
        """测试按标签获取"""
        url1 = "https://example1.com/subscribe"
        url2 = "https://example2.com/subscribe"
        
        temp_storage.add_or_update(url1, {'name': '订阅1'})
        temp_storage.add_or_update(url2, {'name': '订阅2'})
        
        temp_storage.add_tag(url1, '主力')
        temp_storage.add_tag(url2, '备用')
        
        main_subs = temp_storage.get_by_tag('主力')
        assert len(main_subs) == 1
        assert url1 in main_subs
    
    def test_get_all_tags(self, temp_storage):
        """测试获取所有标签"""
        url1 = "https://example1.com/subscribe"
        url2 = "https://example2.com/subscribe"
        
        temp_storage.add_or_update(url1, {'name': '订阅1'})
        temp_storage.add_or_update(url2, {'name': '订阅2'})
        
        temp_storage.add_tag(url1, '主力')
        temp_storage.add_tag(url1, 'IPLC')
        temp_storage.add_tag(url2, '备用')
        
        all_tags = temp_storage.get_all_tags()
        assert set(all_tags) == {'主力', 'IPLC', '备用'}
    
    def test_export_import(self, temp_storage):
        """测试导出导入"""
        # 添加测试数据
        url1 = "https://example1.com/subscribe"
        url2 = "https://example2.com/subscribe"
        
        temp_storage.add_or_update(url1, {'name': '订阅1', 'node_count': 5})
        temp_storage.add_or_update(url2, {'name': '订阅2', 'node_count': 10})
        temp_storage.add_tag(url1, '主力')
        
        # 导出
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            export_file = f.name
        
        temp_storage.export_to_file(export_file)
        
        # 创建新存储并导入
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            new_storage_file = f.name
        
        new_storage = SubscriptionStorage(data_file=new_storage_file)
        count = new_storage.import_from_file(export_file, merge=False)
        
        assert count == 2
        assert url1 in new_storage.get_all()
        assert url2 in new_storage.get_all()
        assert '主力' in new_storage.get_all()[url1]['tags']
        
        # 清理
        os.remove(export_file)
        os.remove(new_storage_file)
    
    def test_statistics(self, temp_storage):
        """测试统计功能"""
        url1 = "https://example1.com/subscribe"
        url2 = "https://example2.com/subscribe"
        
        temp_storage.add_or_update(url1, {
            'name': '订阅1',
            'total': 1024**3,
            'remaining': 512**3,
            'expire_time': '2099-12-31 23:59:59'
        })
        temp_storage.add_or_update(url2, {
            'name': '订阅2',
            'total': 2 * 1024**3,
            'remaining': 1024**3,
            'expire_time': '2020-01-01 00:00:00'  # 已过期
        })
        
        temp_storage.add_tag(url1, '主力')
        temp_storage.add_tag(url2, '备用')
        
        stats = temp_storage.get_statistics()
        
        assert stats['total'] == 2
        assert stats['expired'] == 1
        assert stats['active'] == 1
        assert len(stats['tags']) == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
