"""
单元测试 - 解析器模块
"""

import pytest
from unittest.mock import Mock, patch
from parser import SubscriptionParser


class TestSubscriptionParser:
    """订阅解析器测试"""
    
    @pytest.fixture
    def parser(self):
        """创建解析器实例"""
        return SubscriptionParser(use_proxy=False)
    
    def test_extract_node_name_from_hash(self, parser):
        """测试从 # 提取节点名"""
        line = "ss://xxxxx#香港-01"
        name = parser._extract_node_name(line, "ss://")
        assert name == "香港-01"
    
    def test_extract_node_name_url_encoded(self, parser):
        """测试 URL 编码的节点名"""
        line = "ss://xxxxx#%E9%A6%99%E6%B8%AF-01"  # 香港-01 的 URL 编码
        name = parser._extract_node_name(line, "ss://")
        assert "香港" in name
    
    def test_parse_node_line_ss(self, parser):
        """测试解析 SS 节点"""
        line = "ss://xxxxx#香港-01"
        node = parser._parse_node_line(line)
        
        assert node is not None
        assert node['protocol'] == 'ss'
        assert node['name'] == '香港-01'
    
    def test_parse_node_line_vmess(self, parser):
        """测试解析 VMess 节点"""
        line = "vmess://xxxxx#美国-02"
        node = parser._parse_node_line(line)
        
        assert node is not None
        assert node['protocol'] == 'vmess'
    
    def test_parse_node_line_invalid(self, parser):
        """测试无效节点"""
        line = "invalid node format"
        node = parser._parse_node_line(line)
        
        assert node is None
    
    def test_analyze_nodes_countries(self, parser):
        """测试节点国家统计"""
        nodes = [
            {'name': '香港-01', 'protocol': 'ss'},
            {'name': '香港-02', 'protocol': 'ss'},
            {'name': '美国-01', 'protocol': 'vmess'},
            {'name': '日本-01', 'protocol': 'trojan'},
        ]
        
        stats = parser._analyze_nodes(nodes)
        
        assert stats['countries']['香港'] == 2
        assert stats['countries']['美国'] == 1
        assert stats['countries']['日本'] == 1
    
    def test_analyze_nodes_protocols(self, parser):
        """测试节点协议统计"""
        nodes = [
            {'name': '节点1', 'protocol': 'ss'},
            {'name': '节点2', 'protocol': 'ss'},
            {'name': '节点3', 'protocol': 'vmess'},
        ]
        
        stats = parser._analyze_nodes(nodes)
        
        assert stats['protocols']['ss'] == 2
        assert stats['protocols']['vmess'] == 1
    
    def test_parse_traffic_info(self, parser):
        """测试流量信息解析"""
        headers = {
            'subscription-userinfo': 'upload=1000; download=2000; total=10000; expire=1735689600'
        }
        
        traffic_info = parser._parse_traffic_info(headers)
        
        assert traffic_info['upload'] == 1000
        assert traffic_info['download'] == 2000
        assert traffic_info['total'] == 10000
        assert traffic_info['used'] == 3000
        assert traffic_info['remaining'] == 7000
        assert 'expire_time' in traffic_info
    
    def test_parse_traffic_info_no_header(self, parser):
        """测试无流量信息头"""
        headers = {}
        traffic_info = parser._parse_traffic_info(headers)
        
        assert traffic_info == {}
    
    @patch('requests.Session.get')
    def test_download_subscription_with_retry(self, mock_get, parser):
        """测试下载订阅（带重试）"""
        # 模拟响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "test content"
        mock_response.headers = {}
        mock_get.return_value = mock_response
        
        response = parser._download_subscription("https://example.com/subscribe")
        
        assert response.text == "test content"
        assert mock_get.called


class TestNodeParsing:
    """节点解析测试"""
    
    @pytest.fixture
    def parser(self):
        return SubscriptionParser(use_proxy=False)
    
    def test_parse_base64_nodes(self, parser):
        """测试 Base64 格式节点解析"""
        import base64
        
        # 创建测试节点
        nodes_text = "ss://xxxxx#香港-01\nvmess://yyyyy#美国-02"
        encoded = base64.b64encode(nodes_text.encode()).decode()
        
        nodes = parser._parse_nodes(encoded)
        
        assert len(nodes) == 2
        assert nodes[0]['protocol'] == 'ss'
        assert nodes[1]['protocol'] == 'vmess'
    
    def test_parse_clash_yaml_nodes(self, parser):
        """测试 Clash YAML 格式解析"""
        yaml_content = """
proxies:
  - name: 香港-01
    type: ss
    server: example.com
    port: 8388
  - name: 美国-02
    type: vmess
    server: example2.com
    port: 443
"""
        
        nodes = parser._parse_nodes(yaml_content)
        
        assert len(nodes) == 2
        assert nodes[0]['name'] == '香港-01'
        assert nodes[0]['protocol'] == 'ss'
        assert nodes[1]['name'] == '美国-02'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

