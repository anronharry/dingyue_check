"""TXT import and export helpers for SSNodeConverter."""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable, Iterator
from typing import Any


ParseLine = Callable[[str], dict[str, Any] | None]
BuildUrl = Callable[[dict[str, Any]], str | None]
MetadataCallback = Callable[[str, str], None]


def iter_txt_file(
    file_path: str, parse_line: ParseLine, set_metadata: MetadataCallback
) -> Iterator[dict[str, Any]]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            first_line_checked = False
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                if not first_line_checked:
                    first_line_checked = True
                    if parse_metadata_line(line, set_metadata):
                        continue
                node = parse_line(line)
                if node:
                    yield node
    except Exception as exc:
        print(f"读取txt文件失败: {exc}")


def parse_txt_file(
    file_path: str, parse_line: ParseLine, set_metadata: MetadataCallback
) -> tuple[bool, list[dict[str, Any]]]:
    try:
        nodes = list(iter_txt_file(file_path, parse_line, set_metadata))
        print(f"成功解析 {len(nodes)} 个节点")
        return len(nodes) > 0, nodes
    except Exception as exc:
        print(f"解析txt文件失败: {exc}")
        return False, []


def to_txt(
    *,
    output_file: str,
    nodes: list[dict[str, Any]],
    remarks: str,
    status: str,
    build_url: BuildUrl,
) -> bool:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        exported, skipped = write_txt_file(output_file, nodes, remarks, status, build_url)
        skip_msg = f"，跳过 {skipped} 个不支持的节点" if skipped else ""
        print(f"成功导出到 txt 文件: {output_file}（共 {exported} 个节点{skip_msg}）")
        return exported > 0
    except OSError as exc:
        print(f"导出 txt 文件失败(文件系统错误): {exc}")
        return False


def to_v2rayn_base64(*, output_file: str, nodes: list[dict[str, Any]], build_url: BuildUrl) -> bool:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        urls = [url for node in nodes if (url := build_url(node))]
        if not urls:
            print("⚠️  没有可导出的有效节点")
            return False
        content = "\n".join(urls)
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        with open(output_file, "w", encoding="utf-8") as handle:
            handle.write(encoded)
        print(f"✅ 成功导出 v2rayN 订阅格式: {output_file} ({len(urls)} 个节点)")
        return True
    except OSError as exc:
        print(f"导出 v2rayN 格式失败(文件系统错误): {exc}")
        return False


def parse_metadata_line(line: str, set_metadata: MetadataCallback) -> bool:
    if not line.startswith("REMARKS="):
        return False
    match = re.search(r"REMARKS=(.+?)(?:\s+STATUS=(.+))?$", line)
    if match:
        set_metadata(match.group(1), match.group(2) or "")
    return True


def write_txt_file(
    output_file: str,
    nodes: list[dict[str, Any]],
    remarks: str,
    status: str,
    build_url: BuildUrl,
) -> tuple[int, int]:
    exported, skipped = 0, 0
    with open(output_file, "w", encoding="utf-8") as handle:
        write_metadata(handle, remarks, status)
        for node in nodes:
            url = build_url(node)
            if url:
                handle.write(url + "\n")
                exported += 1
            else:
                skipped += 1
    return exported, skipped


def write_metadata(handle, remarks: str, status: str) -> None:
    if not (remarks or status):
        return
    line = f"REMARKS={remarks}"
    if status:
        line += f" STATUS={status}"
    handle.write(line + "\n")


__all__ = ["iter_txt_file", "parse_txt_file", "to_txt", "to_v2rayn_base64"]
