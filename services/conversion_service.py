"""Conversion and deep-check service helpers."""

from __future__ import annotations

import os
import time

from core.converters.ss_converter import SSNodeConverter


class ConversionService:
    def __init__(self, *, workspace_manager, latency_runner):
        self.workspace_manager = workspace_manager
        self.latency_runner = latency_runner

    def convert_txt_bytes_to_yaml(self, *, file_name: str, content_bytes: bytes) -> dict:
        raw_path = self.workspace_manager.save_raw_file(file_name, content_bytes)
        converter = SSNodeConverter()
        if not converter.parse_txt_file(raw_path):
            return {"ok": False, "error": "未找到有效节点"}

        output_name = f"{file_name.rsplit('.', 1)[0]}.yaml"
        output_path = os.path.join(self.workspace_manager.yaml_dir, output_name)
        if not converter.to_yaml(output_path):
            return {"ok": False, "error": "YAML 生成失败"}

        return {"ok": True, "output_name": output_name, "output_path": output_path}

    def convert_yaml_bytes_to_txt(self, *, file_name: str, content_bytes: bytes) -> dict:
        raw_path = self.workspace_manager.save_raw_file(file_name, content_bytes)
        converter = SSNodeConverter()
        if not converter.parse_yaml_file(raw_path):
            return {"ok": False, "error": "未找到有效节点"}

        output_name = f"{file_name.rsplit('.', 1)[0]}.txt"
        output_path = os.path.join(self.workspace_manager.txt_dir, output_name)
        if not converter.to_txt(output_path):
            return {"ok": False, "error": "TXT 生成失败"}

        return {"ok": True, "output_name": output_name, "output_path": output_path}

    async def run_deepcheck(self, *, file_name: str, content_bytes: bytes, status_callback) -> dict:
        target_file = self.workspace_manager.save_raw_file(file_name, content_bytes)
        before_run = time.time()

        await self.latency_runner(
            [target_file],
            mode="auto",
            clean_policy="no",
            export_policy="yes",
            status_callback=status_callback,
        )

        latest_path = self._find_latest_yaml_export(min_mtime=before_run)
        if not latest_path:
            return {"ok": True, "output_path": None, "output_name": None}

        return {
            "ok": True,
            "output_path": latest_path,
            "output_name": os.path.basename(latest_path),
        }

    def _find_latest_yaml_export(self, *, min_mtime: float) -> str | None:
        yaml_dir = self.workspace_manager.yaml_dir
        if not os.path.isdir(yaml_dir):
            return None

        candidates = []
        for name in os.listdir(yaml_dir):
            path = os.path.join(yaml_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime >= min_mtime:
                candidates.append((mtime, path))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        return candidates[0][1]
