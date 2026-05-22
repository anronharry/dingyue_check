#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SS协议节点转换工具
支持SS协议txt文件与yaml格式的双向转换
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, Optional
from core.models import ProxyNode
from core.converters.protocols import shadowsocks
from core.converters.protocols import shadowsocksr
from core.converters.protocols import trojan
from core.converters.protocols import vless
from core.converters.protocols import vmess
from core.converters import txt_export, yaml_export


class SSNodeConverter:
    """SS节点转换器类"""

    def __init__(self):
        self.nodes = []
        self.remarks = ""
        self.status = ""

    def parse_vmess_url(self, vmess_url: str) -> Optional[ProxyNode]:
        """
        解析单条 Vmess 协议 URL
        """
        return vmess.parse_vmess_url(vmess_url)

    def parse_trojan_url(self, trojan_url: str) -> Optional[ProxyNode]:
        """
        解析单条 Trojan 协议 URL
        """
        return trojan.parse_trojan_url(trojan_url)

    def parse_vless_url(self, vless_url: str) -> Optional[ProxyNode]:
        """
        解析单条 VLESS 协议 URL
        格式: vless://uuid@server:port?type=...&security=...#name
        """
        return vless.parse_vless_url(vless_url)

    def parse_ss_url(self, ss_url: str) -> Optional[ProxyNode]:
        """
        解析单个SS协议URL
        """
        return shadowsocks.parse_ss_url(ss_url)

    def iter_txt_file(self, file_path: str):
        """
        以流式生成器逐行解析txt文件中的协议链接，极大降低内存占用。
        """
        return txt_export.iter_txt_file(file_path, self._parse_protocol_line, self._set_metadata)

    def parse_txt_file(self, file_path: str) -> bool:
        """
        兼容遗留 API: 将所有的生成器结果收集至 self.nodes 列表中。
        """
        ok, new_nodes = txt_export.parse_txt_file(
            file_path, self._parse_protocol_line, self._set_metadata
        )
        self.nodes.extend(new_nodes)
        return ok

    def _set_metadata(self, remarks: str, status: str) -> None:
        self.remarks = remarks
        self.status = status

    def _parse_protocol_line(self, line: str) -> Optional[ProxyNode]:
        if line.startswith("ss://"):
            return self.parse_ss_url(line)
        if line.startswith("ssr://"):
            return self.parse_ssr_url(line)
        if line.startswith("vmess://"):
            return self.parse_vmess_url(line)
        if line.startswith("trojan://"):
            return self.parse_trojan_url(line)
        if line.startswith("vless://"):
            return self.parse_vless_url(line)
        return None

    def to_yaml(self, output_file: str, full_config: bool = True) -> bool:
        """
        将节点导出为yaml格式
        """
        return yaml_export.to_yaml(
            output_file=output_file,
            nodes=self.nodes,
            remarks=self.remarks,
            status=self.status,
            full_config=full_config,
        )

    def build_ss_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建SS协议URL
        """
        return shadowsocks.build_ss_url(node)

    def parse_yaml_file(self, file_path: str) -> bool:
        """
        解析 yaml 文件
        """
        ok, nodes, remarks, status = yaml_export.parse_yaml_file(file_path)
        if ok:
            self.nodes = nodes
            self.remarks = remarks
            self.status = status
        return ok

    def build_vmess_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建 Vmess 协议 URL（vmess://BASE64_JSON）

        Args:
            node: 节点信息字典（type 必须为 'vmess'）

        Returns:
            vmess:// URL 字符串，构建失败返回 None
        """
        return vmess.build_vmess_url(node)

    def build_trojan_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建 Trojan 协议 URL

        Args:
            node: 节点信息字典（type 必须为 'trojan'）

        Returns:
            trojan:// URL 字符串，构建失败返回 None
        """
        return trojan.build_trojan_url(node)

    def build_vless_url(self, node: Dict) -> Optional[str]:
        """
        构建 VLESS 协议 URL
        格式: vless://uuid@server:port?type=...&security=...#name
        """
        return vless.build_vless_url(node)

    def parse_ssr_url(self, ssr_url: str) -> Optional[ProxyNode]:
        """
        解析单条 SSR (ShadowsocksR) 协议 URL
        """
        return shadowsocksr.parse_ssr_url(ssr_url)

    def build_ssr_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建 SSR 协议 URL
        """
        return shadowsocksr.build_ssr_url(node)

    def build_url(self, node: Dict) -> Optional[str]:
        """
        按节点协议类型自动分派，构建对应格式的 URL。
        支持 ss / ssr / vmess / trojan / vless。
        """
        ntype = str(node.get("type", "")).lower()
        if ntype == "ss":
            return self.build_ss_url(node)
        elif ntype == "ssr":
            return self.build_ssr_url(node)
        elif ntype == "vmess":
            return self.build_vmess_url(node)
        elif ntype == "trojan":
            return self.build_trojan_url(node)
        elif ntype == "vless":
            return self.build_vless_url(node)
        else:
            print(f"⚠️  跳过不支持导出的协议节点: {node.get('name', '?')} (type={ntype})")
            return None

    def to_txt(self, output_file: str) -> bool:
        """
        将节点导出为协议 URL txt 格式（支持 ss / ssr / vmess / trojan 混合导出）
        """
        return txt_export.to_txt(
            output_file=output_file,
            nodes=self.nodes,
            remarks=self.remarks,
            status=self.status,
            build_url=self.build_url,
        )

    def to_v2rayn_base64(self, output_file: str) -> bool:
        """
        将节点导出为 v2rayN 兼容的 Base64 订阅格式
        """
        return txt_export.to_v2rayn_base64(
            output_file=output_file, nodes=self.nodes, build_url=self.build_url
        )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="SS协议节点转换工具 - 支持txt和yaml格式的双向转换",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # txt转yaml
  python ss_converter.py -i nodes.txt -o nodes.yaml
  
  # yaml转txt
  python ss_converter.py -i nodes.yaml -o nodes.txt
  
  # 自动检测格式
  python ss_converter.py -i input.txt -o output.yaml
        """,
    )

    parser.add_argument("-i", "--input", required=True, help="输入文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出文件路径")
    parser.add_argument(
        "-f", "--format", choices=["txt", "yaml"], help="指定输入文件格式(可选,默认自动检测)"
    )

    args = parser.parse_args()

    # 创建转换器实例
    converter = SSNodeConverter()

    # 检测输入文件格式
    input_format = args.format
    if not input_format:
        if args.input.endswith(".yaml") or args.input.endswith(".yml"):
            input_format = "yaml"
        else:
            input_format = "txt"

    print(f"输入文件格式: {input_format}")

    # 解析输入文件
    if input_format == "txt":
        if not converter.parse_txt_file(args.input):
            print("解析txt文件失败")
            sys.exit(1)
    else:
        if not converter.parse_yaml_file(args.input):
            print("解析yaml文件失败")
            sys.exit(1)

    # 检测输出文件格式
    if args.output.endswith(".yaml") or args.output.endswith(".yml"):
        output_format = "yaml"
    else:
        output_format = "txt"

    print(f"输出文件格式: {output_format}")

    # 导出到目标格式
    if output_format == "yaml":
        if not converter.to_yaml(args.output):
            print("导出yaml文件失败")
            sys.exit(1)
    else:
        if not converter.to_txt(args.output):
            print("导出txt文件失败")
            sys.exit(1)

    print("转换完成!")


if __name__ == "__main__":
    main()
