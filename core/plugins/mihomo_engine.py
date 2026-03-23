
from __future__ import annotations
import os
import sys
import time
import zipfile
import re
import yaml
import base64
import hashlib
import select
import subprocess
import aiohttp
import psutil
import atexit
from colorama import Fore, Style

import config as _cfg

MIHOMO_DIR = os.path.join(str(_cfg.BASE_DIR), 'bin')
MIHOMO_EXE = os.path.join(MIHOMO_DIR, 'mihomo.exe')


def get_sys_arch() -> tuple[str, str]:
    import platform
    sys_name = platform.system().lower()
    arch = platform.machine().lower()
    
    # 针对部分发布包带有 -compatible 尾缀的特殊处理
    if sys_name == "windows":
        target = "windows-amd64-compatible" if "amd64" in arch else "windows-arm-compatible"
        ext = ".zip"
    elif sys_name == "linux":
        target = "linux-amd64-compatible" if "x86_64" in arch else "linux-arm64"
        ext = ".gz" 
    elif sys_name == "darwin":
        target = "darwin-amd64-compatible" if "x86_64" in arch else "darwin-arm64"
        ext = ".gz"
    else:
        target, ext = "windows-amd64-compatible", ".zip" # 降级容灾
    return target, ext

async def get_latest_mihomo_url(session: aiohttp.ClientSession) -> tuple[str, str]:
    """
    获取最新版 Mihomo 的下载链接和对应的 sha256 哈希值。
    返回: (download_url, sha256_url) 元组。如果获取失败则返回备用链接居中。
    """
    target, ext = get_sys_arch()
    try:
        async with session.get("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest", timeout=10) as resp:
            resp.raise_for_status()
            data = await resp.json()
            dl_url = ""
            sha256_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if target in name and name.endswith(ext):
                    dl_url = asset.get("browser_download_url", "")
                if target in name and name.endswith(f"{ext}.sha256sum"):
                    sha256_url = asset.get("browser_download_url", "")
            if dl_url:
                return dl_url, sha256_url
    except Exception as e:
        print(f"获取最新内核链接失败: {e}")
    # 提供备用链接（无 sha256）
    return (
        "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.3/mihomo-windows-amd64-compatible-v1.18.3.zip",
        ""
    )


async def download_mihomo() -> bool:
    """下载并解压 Mihomo，下载完成后进行 sha256 完整性校验。"""
    if os.path.exists(MIHOMO_EXE):
        return True

    os.makedirs(MIHOMO_DIR, exist_ok=True)
    zip_path = os.path.join(MIHOMO_DIR, "mihomo.zip")

    print(f"{Fore.YELLOW}正在初次下载测速引擎 (Mihomo/ClashMeta)...这可能需要几分钟，请耐心等待。{Style.RESET_ALL}")

    async with aiohttp.ClientSession() as session:
        url, sha256_url = await get_latest_mihomo_url(session)
        try:
            async with session.get(url, timeout=300) as response:
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                with open(zip_path, 'wb') as file:
                    async for chunk in response.content.iter_chunked(65536):
                        downloaded += len(chunk)
                        file.write(chunk)
                        if total_size > 0:
                            percent = int(50 * downloaded / total_size)
                            sys.stdout.write(
                                f"\r下载进度: [{'=' * percent}{' ' * (50 - percent)}]"
                                f" {downloaded}/{total_size} Bytes"
                            )
                            sys.stdout.flush()
                        else:
                            sys.stdout.write(f"\r已下载: {downloaded // 1024} KB...")
                            sys.stdout.flush()
                print(f"\n{Fore.GREEN}下载完成，正在校验文件完整性...{Style.RESET_ALL}")

                # sha256 完整性校验
                if sha256_url:
                    try:
                        async with session.get(sha256_url, timeout=15) as sha_resp:
                            sha_resp.raise_for_status()
                            sha_text = await sha_resp.text()
                            expected_hash = sha_text.strip().split()[0].lower()
                            
                            h = hashlib.sha256()
                            with open(zip_path, 'rb') as hf:
                                for chunk in iter(lambda: hf.read(65536), b''):
                                    h.update(chunk)
                            actual_hash = h.hexdigest().lower()
                            
                            if actual_hash != expected_hash:
                                print(f"{Fore.RED}❌ sha256 校验失败！文件可能已损墙，拒绝使用。{Style.RESET_ALL}")
                                os.remove(zip_path)
                                return False
                            print(f"{Fore.GREEN}✔ sha256 校验通过，正在解压...{Style.RESET_ALL}")
                    except Exception as e:
                        print(f"{Fore.YELLOW}⚠️  无法执行 sha256 校验（{e}），跳过校验继续安装。{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}⚠️  未找到对应 sha256 资产，跳过完整性校验。{Style.RESET_ALL}")

                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    exe_files = [name for name in zip_ref.namelist() if name.endswith('.exe')]
                    if not exe_files:
                        raise RuntimeError("压缩包中未找到 .exe 文件")
                    exe_name = exe_files[0]
                    zip_ref.extract(exe_name, MIHOMO_DIR)
                    extracted_path = os.path.join(MIHOMO_DIR, exe_name)
                    if os.path.exists(MIHOMO_EXE):
                        os.remove(MIHOMO_EXE)
                    os.rename(extracted_path, MIHOMO_EXE)

                os.remove(zip_path)
                print(f"{Fore.GREEN}✅ 内核初始化成功！{Style.RESET_ALL}\n")
                return True
        except Exception as e:
            print(f"\n{Fore.RED}❌ 下载或解压内核失败: {e}{Style.RESET_ALL}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            return False


def kill_process_tree(pid: int):
    """递归清理进程及其所有子进程，解决内核后台逃逸问题"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        # 先杀子进程
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        # 再杀父进程
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass
    except psutil.NoSuchProcess:
        pass

def kill_orphan_mihomo() -> None:
    """清理可能残留的孤儿 Mihomo 进程，根据精细的规则判断"""
    try:
        curr_proc_dir = os.path.abspath(_cfg.BASE_DIR)
        for _p in psutil.process_iter(['name', 'exe', 'pid']):
            try:
                name = _p.info.get('name', '')
                exe = _p.info.get('exe', '')
                if name and 'mihomo' in name.lower():
                    # 基于 exe 路径精确捕获属于本项目 bin 目录内的 mihomo，避免误杀用户系统的 Clash
                    if exe and os.path.abspath(exe).startswith(curr_proc_dir):
                        kill_process_tree(_p.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        pass
    except Exception as e:
        from core.session_logger import get_logger
        get_logger().print_warning(f"清理孤儿 Mihomo 进程时出现异常: {e}")

# 注册到 atexit，主进程退出时自动清理相关 Mihomo 进程
atexit.register(kill_orphan_mihomo)


def _read_errors(p) -> list:
    """内部函数：读取 Mihomo 日志中的错误行，避免阻塞。"""
    try:
        if sys.platform != "win32":
            r, _, _ = select.select([p.stdout], [], [], 0.1)
            if not r: return []
        
        out, _ = p.communicate(timeout=0.5)
        text = out.decode("utf-8", errors="replace") if out else ""
        return [l for l in text.splitlines() if "fatal" in l.lower() or "error" in l.lower()]
    except (OSError, ValueError, UnicodeDecodeError):
        return []


async def run_mihomo(nodes: list, state: dict, config_path: str, session: aiohttp.ClientSession) -> bool:
    """
    保证 Mihomo 以给定节点配置运行。
    使用 aiohttp 检查 API 就绪状态。
    """
    _MAX_RETRIES = 2
    api_base = f"http://127.0.0.1:{_cfg.API_PORT}"

    # SS2022 密码质量预校验
    _SS2022 = {
        '2022-blake3-aes-128-gcm':       16,
        '2022-blake3-aes-256-gcm':        32,
        '2022-blake3-chacha20-poly1305': 32,
    }
    valid_nodes, skipped = [], 0
    for node in nodes:
        if node.get('type') == 'ss' and node.get('cipher') in _SS2022:
            req = _SS2022[node['cipher']]
            try:
                import binascii
                key = base64.b64decode(str(node.get('password', '')) + '==')
                if len(key) != req:
                    skipped += 1
                    continue
            except (ValueError, TypeError, binascii.Error):
                skipped += 1
                continue
        valid_nodes.append(node)

    if skipped:
        print(f"{Fore.YELLOW}  ⚠️  跳过 {skipped} 个 SS2022 密码不合法的节点{Style.RESET_ALL}")

    nodes = valid_nodes
    if not nodes:
        print(f"{Fore.RED}  ❌ 所有节点因 SS2022 密码格式不合法被跳过，无法启动内核。{Style.RESET_ALL}")
        return False

    # 写入临时配置
    cfg_data = {
        "external-controller": f"127.0.0.1:{_cfg.API_PORT}",
        "mode":      "rule",
        "log-level": "silent",
        "proxies":   nodes,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg_data, f, allow_unicode=True, sort_keys=False)

    for attempt in range(_MAX_RETRIES + 1):
        proc = state.get('proc')

        if proc is None or proc.poll() is not None:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            new_proc = subprocess.Popen(
                [MIHOMO_EXE, "-f", config_path],
                cwd=str(_cfg.BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            state['proc'] = new_proc
            wait, total_waited, max_wait = 0.2, 0.0, 12.0
            while total_waited < max_wait:
                await asyncio.sleep(wait)
                total_waited += wait
                if new_proc.poll() is not None:
                    break
                try:
                    async with session.get(f"{api_base}/version", timeout=1) as resp:
                        if resp.status == 200:
                            return True
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                wait = min(wait * 1.5, 1.5)

            if attempt < _MAX_RETRIES:
                state['proc'] = None
            continue

        # 情况B：热重载配置
        try:
            async with session.put(
                f"{api_base}/configs?force=true",
                json={"path": os.path.abspath(config_path)},
                timeout=5,
            ) as resp:
                if resp.status in (200, 204):
                    await asyncio.sleep(0.5)
                    try:
                        async with session.get(f"{api_base}/version", timeout=1) as v_resp:
                            if v_resp.status == 200:
                                return True
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        pass
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

        try:
            proc.terminate()
            proc.wait(timeout=3)
        except OSError:
            pass
        state['proc'] = None

    return False


import asyncio
import aiohttp
import urllib.parse
from core.plugins.base_engine import BaseTestEngine

class MihomoEngine(BaseTestEngine):
    """
    基于 Mihomo/ClashMeta 的测速引擎实现。
    使用 aiohttp 进行全异步通信。
    """
    def __init__(self):
        self._state = {'proc': None}
        self.api_port = _cfg.API_PORT
        self.api_base = f"http://127.0.0.1:{self.api_port}"

    @property
    def engine_name(self) -> str:
        return "Mihomo(ClashMeta)"

    async def prepare(self) -> bool:
        """异步准备内核"""
        kill_orphan_mihomo()
        if os.path.exists(MIHOMO_EXE):
            if os.path.getsize(MIHOMO_EXE) < 1024 * 1024:
                try:
                    os.remove(MIHOMO_EXE)
                except Exception:
                    pass
        return await download_mihomo()

    async def start(self, nodes: list, port: int, session: aiohttp.ClientSession) -> bool:
        """异步启动内核"""
        self.api_port = port
        self.api_base = f"http://127.0.0.1:{self.api_port}"
            
        temp_dir = _cfg.BASE_DIR / _cfg.TEMP_DIR_NAME
        temp_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = str(temp_dir / f"temp_mihomo_cfg_{os.getpid()}.yaml")
            
        return await run_mihomo(nodes, self._state, self._config_path, session)

    def stop(self) -> None:
        """停止内核并释放资源"""
        proc = self._state.get('proc')
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except OSError:
                pass
        self._state['proc'] = None
        
        if hasattr(self, '_config_path') and os.path.exists(self._config_path):
            try:
                os.remove(self._config_path)
            except OSError:
                pass

    async def async_test_node(self, node_name: str, timeout_ms: int, test_url: str, session: aiohttp.ClientSession, sem: asyncio.Semaphore) -> dict:
        """发起异步并发测速请求"""
        async with sem:
            encoded_name = urllib.parse.quote(node_name)
            url = f"{self.api_base}/proxies/{encoded_name}/delay?timeout={timeout_ms}&url={urllib.parse.quote(test_url)}"
            try:
                async with session.get(url, timeout=timeout_ms / 1000 + 2) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        delay = data.get("delay", -1)
                        if delay == 0: delay = 1
                        return {"name": node_name, "status": "valid", "delay": delay}
                    else:
                        return {"name": node_name, "status": "error", "error": f"HTTP {resp.status}"}
            except asyncio.TimeoutError:
                return {"name": node_name, "status": "error", "error": "TimeoutError"}
            except aiohttp.ClientError as e:
                return {"name": node_name, "status": "error", "error": type(e).__name__}
