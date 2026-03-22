import os
import time
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)

import config as _cfg

from rich.console import Console
from rich.panel import Panel

console = Console()

def clear_screen():
    """清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    """打印标题"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    content = (
        f"[bold cyan]🛡️  代理节点管理工具  🛡️[/]\n"
        f"[white]SS / Vmess / Trojan / Vless 节点测速 · 订阅检测 · 格式转换[/]\n"
        f"[dim]📅 {now}[/]"
    )
    console.print(Panel(content, border_style="cyan", expand=False))


# 文件列表短缓存（减少菜单频繁刷新时的磁盘扫描）
_LIST_FILES_CACHE = {}
_LIST_FILES_TTL_SEC = 1.2

def list_files(extension=None):
    """列出对应文件夹下的文件 (支持元组拓展名，从不同的指定文件夹收集)"""
    ext_tuple = extension if isinstance(extension, tuple) else ((extension,) if extension else None)
    cache_key = tuple(sorted(ext_tuple)) if ext_tuple else None
    now = time.monotonic()
    cached = _LIST_FILES_CACHE.get(cache_key)
    if cached and (now - cached['ts'] <= _LIST_FILES_TTL_SEC):
        return cached['files']

    files = []
    TXT_FOLDER = str(_cfg.BASE_DIR / _cfg.TXT_FOLDER)
    YAML_FOLDER = str(_cfg.BASE_DIR / _cfg.YAML_FOLDER)
    
    # 辅助方法:从固定特征文件夹安全寻找匹配后缀的文件
    def scan_dir(target_dir, valid_exts):
        if not os.path.exists(target_dir):
            return
        for f in os.listdir(target_dir):
            if os.path.isfile(os.path.join(target_dir, f)):
                if valid_exts is None:
                    files.append(os.path.join(target_dir, f))
                else:
                    if any(f.endswith(ext) for ext in valid_exts):
                        files.append(os.path.join(target_dir, f))
                        
    if ext_tuple:
        if any('.txt' in ext for ext in ext_tuple):
            scan_dir(TXT_FOLDER, ext_tuple)
        if any(e in ext_tuple for e in ['.yaml', '.yml']):
            scan_dir(YAML_FOLDER, ext_tuple)
            
        # 如果什么特殊目录都不沾边（比如未来扩展别的格式），扫根目录
        if len(files) == 0:
            scan_dir('.', ext_tuple)
    else:
        # None 的情况全搜
        scan_dir(TXT_FOLDER, None)
        scan_dir(YAML_FOLDER, None)
        scan_dir('.', None)
    
    out = sorted(list(set(files)))
    _LIST_FILES_CACHE[cache_key] = {'ts': now, 'files': out}
    return out


def parse_index_selection(choice: str, total: int) -> list[int]:
    """
    #4 公共辅助函数：解析用户输入的文件编号为 1-based 索引列表。
    支持格式：
      - 'all'     → [1, 2, ..., total]
      - '1'       → [1]
      - '1,3,5'   → [1, 3, 5]
      - '2-5'     → [2, 3, 4, 5]
      - 混合如 '1,3-5' → [1, 3, 4, 5]
    返回已过滤到 [1, total] 范围内的有效索引列表（升序）。
    """
    if choice.strip().lower() == 'all':
        return list(range(1, total + 1))
    indices: set[int] = set()
    for part in choice.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1)
            if a.isdigit() and b.isdigit():
                lo, hi = int(a), int(b)
                if lo > hi:
                    lo, hi = hi, lo
                for i in range(lo, hi + 1):
                    indices.add(i)
        elif part.isdigit():
            indices.add(int(part))
    return sorted(i for i in indices if 1 <= i <= total)


def select_files(prompt, extension=None):
    """让用户批量选择文件(借助于原生输入)"""
    files = list_files(extension)

    if not files:
        if extension:
            if isinstance(extension, tuple):
                ext_msg = f"（{'/'.join(extension)}）"
            else:
                ext_msg = f"（{extension}）"
        else:
            ext_msg = ""
        print(f"❌ 当前目录下没有找到文件{ext_msg}")
        return []

    # 解析文件类型
    txt_files_to_detect = [f for f in files if os.path.splitext(f)[1].lower() not in ('.yaml', '.yml')]
    mode_results = {}
    if txt_files_to_detect:
        try:
            from core.node_tester import auto_detect_file_mode
            for f in txt_files_to_detect:
                mode_results[f] = auto_detect_file_mode(f)
        except ImportError:
            pass
            
    print(f"\n{prompt}")
    for i, f in enumerate(files, 1):
        size = os.path.getsize(f)
        size_str = f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB"
        ext = os.path.splitext(f)[1].lower()
        if ext in ('.yaml', '.yml'):
            type_tag = "[🔗直接节点]"
        else:
            fm = mode_results.get(f, 'direct')
            type_tag = "[📶URL订阅]" if fm == 'url' else "[🔗直接节点]"
        
        display_str = f"[{i}] {os.path.basename(f)} {type_tag} ({size_str})"
        print(f"  {display_str}")

    choice = input("\n请选择序号 (例如: 1 或 1,3,5 或 1-5 或 all): ").strip()
    if not choice:
        print("\n\n操作已取消")
        return []
        
    indices = parse_index_selection(choice, len(files))
    if not indices:
        print("❌ 无效的选项组合")
        return []
        
    selected_files = [files[j-1] for j in indices]
    print(f"✅ 成功选择了 {len(selected_files)} 个文件。")
    return selected_files


def pause_for_continue(prompt="\n按回车键继续..."):
    """安全地等待用户按回车（捕获 Ctrl+C 以防报错退出）"""
    try:
        input(prompt)
    except KeyboardInterrupt:
        pass

