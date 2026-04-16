from __future__ import annotations

import os
import gc
import re
import sys
import time
import json
import base64
import glob
import shutil
import yaml
import zipfile
import subprocess
import unicodedata
import asyncio
import importlib
from pathlib import Path
from dataclasses import dataclass
# from tqdm import tqdm
from core.converters.ss_converter import SSNodeConverter
from core.session_logger import get_logger
from app import config as _cfg

# init(autoreset=True)

MIHOMO_DIR = os.path.join(str(_cfg.BASE_DIR), 'bin')
MIHOMO_EXE = os.path.join(MIHOMO_DIR, 'mihomo.exe')

print_lock = asyncio.Lock()

# 归档目录：存放全节点失效的文件，供用户手动审查删除
# 路径通过 config.OLD_FILE_DIR_NAME 统一管理，避免硬编码
# 使用 Path 对象以支持 / 路径拼接运算符
OLD_FILE_DIR = Path(_cfg.BASE_DIR) / _cfg.OLD_FILE_DIR_NAME

# ── 显示相关命名常量 ──────────────────────────────────────
_NAME_TRUNCATE_LEN = 60   # 节点名称在测速输出中的最大字符数
_DISP_TARGET_WIDTH = 65   # 终端对齐的目标显示宽度（含全角字符）
_SUMMARY_NAME_LEN  = 40   # 汇总表格中文件名最大显示长度


def _get_display_width(text: str) -> int:
    """
    计算字符串在终端的实际显示宽度（CJK/Emoji 按 2 格计算）。
    适用于含中文、全角字符或 Emoji 的节点名对齐输出。
    """
    width = 0
    for c in text:
        if unicodedata.east_asian_width(c) in ('F', 'W'):
            width += 2
        elif ord(c) > 0x1F000:  # 粗略判断 Emoji 或特殊符号
            width += 2
        else:
            width += 1
    return width





def archive_to_old_file(filepath: str, reason: str = "全节点失效") -> str:
    """内部辅助：将原始文件转移到存档目录并重命名（OLD_FILE_DIR 为 Path 对象，支持 / 运算符）"""
    from datetime import datetime
    p = Path(filepath)
    name = p.stem
    ext = p.suffix
    date_tag = datetime.now().strftime("%Y-%m-%d")

    # 确保归档目录存在
    OLD_FILE_DIR.mkdir(parents=True, exist_ok=True)

    # 简易去重：若同名文件已存在则加序号后缀
    new_name = f"{name}_[{reason}_{date_tag}]{ext}"
    new_path = OLD_FILE_DIR / new_name
    counter = 1
    while new_path.exists():
        new_name = f"{name}_[{reason}_{date_tag}_{counter}]{ext}"
        new_path = OLD_FILE_DIR / new_name
        counter += 1

    try:
        shutil.move(str(filepath), str(new_path))
        return str(new_path)
    except OSError as e:
        print(f"{Fore.RED}❌ 归档失败: {e}{Style.RESET_ALL}")
        return ""

from core.plugins.mihomo_engine import MihomoEngine
from core.plugins.base_engine import BaseTestEngine

import aiohttp
import asyncio
from core.models import NodeTestResult

# 文件类型检测缓存：{filepath: (mtime, mode)}，避免未修改的文件重复读取磁盘
_file_mode_cache: dict = {}


def auto_detect_file_mode(filepath: str) -> str:
    """
    自动检测文件内容类型，决定节点提取模式（只读前 8KB，并缓存结果）

    Returns:
        'direct' — 文件直接包含节点协议链接 (ss/vmess/trojan 等)
        'url'    — 文件主要包含 http/https 订阅链接
    """
    from conf.config import DETECT_READ_BYTES
    PROXY_SCHEMES = ('ss://', 'vmess://', 'trojan://', 'vless://', 'ssr://', 'hysteria://', 'tuic://')

    # YAML/YML 文件必定是 Clash 配置格式，强制 direct
    ext = os.path.splitext(filepath)[1].lower()
    if ext in ('.yaml', '.yml'):
        return 'direct'

    # 基于修改时间+文件大小的缓存：两者均未变化时直接返回上次结果
    # 加入 size 是为了兼容 FAT32/部分 NTFS 上 mtime 精度不足 2 秒的场景
    try:
        mtime = os.path.getmtime(filepath)
        fsize = os.path.getsize(filepath)
        cached = _file_mode_cache.get(filepath)
        if cached and cached[0] == mtime and cached[1] == fsize:
            return cached[2]
    except OSError:
        pass

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(DETECT_READ_BYTES)

        node_lines = sum(1 for line in content.splitlines()
                         if any(line.strip().startswith(s) for s in PROXY_SCHEMES))
        url_links = len(re.findall(r'(?<![a-z])https?://[^\s<>"]+', content))

        if node_lines >= url_links and node_lines > 0:
            mode = 'direct'
        elif url_links > 0:
            mode = 'url'
        else:
            mode = 'direct'
    except OSError:
        mode = 'direct'

    # 写入缓存：(mtime, size, mode)
    try:
        _file_mode_cache[filepath] = (os.path.getmtime(filepath), os.path.getsize(filepath), mode)
    except OSError:
        pass
    return mode


# ═══════════════════════════════════════════════════════════════
# 辅助函数区 — 被 _handle_url_file / _process_single_file / run_node_latency_test 调用
# ───────────────────────────────────────────────────────────────

from core.subscription_manager import async_fetch_nodes_from_subscriptions


def _archive_file(filepath: str, reason: str = "全节点失效") -> str:
    """archive_to_old_file 的短别名，供模块内部统一调用。"""
    return archive_to_old_file(filepath, reason)


def _fmt_name(name: str, maxlen: int = 30) -> str:
    """将节点名称截断到 maxlen 字符，超出部分用 … 替代，用于终端对齐显示。"""
    if len(name) <= maxlen:
        return name
    return name[:maxlen - 1] + "…"


def _ask_batch_policy(prompt: str, opt_yes: str, opt_no: str) -> str:
    """
    批量处理策略询问：让用户选择对所有文件统一执行 yes/no/逐个询问。
    返回 'yes' | 'no' | 'ask'
    """
    print(f"\n{Fore.CYAN}{prompt}{Style.RESET_ALL}")
    print(f"  [y] {opt_yes}")
    print(f"  [n] {opt_no}")
    print(f"  [回车] 对每个文件单独询问")
    choice = input("请选择 [y/n/回车]: ").strip().lower()
    if choice == 'y':
        return 'yes'
    elif choice == 'n':
        return 'no'
    return 'ask'


def _print_batch_summary(batch_summary: list) -> None:
    """打印本次批量测速的汇总结果表格。"""
    if not batch_summary:
        return
    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title="📊 本次批量测速汇总", show_header=True, header_style="bold cyan")
    table.add_column("存活/总数", justify="right")
    table.add_column("状态", justify="center")
    table.add_column("文件名", justify="left")
    
    for rec in batch_summary:
        fname  = _fmt_name(rec.get('file', '?'), _SUMMARY_NAME_LEN)
        total  = rec.get('total', 0)
        valid  = rec.get('valid', 0)
        status = rec.get('status', '')
        ratio  = f"{valid}/{total}"
        
        if status in ('全失效归档', '全失效'):
            color = "[red]"
        elif valid == total and total > 0:
            color = "[green]"
        elif valid > 0:
            color = "[yellow]"
        else:
            color = "[red]"
            
        table.add_row(
            f"{color}{ratio}[/]",
            f"{color}{status}[/]",
            fname
        )
    print()
    console.print(table)
    print()



def _dedup_and_rename(nodes: list[dict]) -> list[dict]:
    """
    节点去重（server+port+type 三元组）并确保名称唯一（重名加 _x 后缀）。
    返回处理后的节点列表。
    """
    seen_eps: set = set()
    deduped:  list = []
    for n in nodes:
        ep = (str(n.get('server', '')).lower(), str(n.get('port', '')), str(n.get('type', '')))
        if ep not in seen_eps:
            seen_eps.add(ep)
            deduped.append(n)
    dup_count = len(nodes) - len(deduped)
    if dup_count > 0:
        print(f"{Fore.YELLOW}🔄 去重: 移除 {dup_count} 个重复节点，剩余 {len(deduped)} 个唯一节点{Style.RESET_ALL}")
    used_names: set = set()
    for idx, node in enumerate(deduped):
        name = str(node.get("name", f"Node_{idx + 1}"))
        while name in used_names:
            name = name + "_x"
        node["name"] = name
        used_names.add(name)
    return deduped


async def _handle_url_file(
        target_file: str,
        sub_session: aiohttp.ClientSession,
        sub_clean_policy: str,
        batch_summary: list) -> None:
    """
    URL 订阅模式：预检订阅有效性、提取节点、询问清理失效订阅、导出有效订阅 TXT。
    结果追加到 batch_summary。
    """
    from datetime import datetime as _dt
    print("  [阶段] 订阅预检与节点提取...")
    final_nodes, invalid_sub_urls, valid_sub_urls = await async_fetch_nodes_from_subscriptions(
        target_file, client_session=sub_session)

    if not final_nodes:
        print(f"{Fore.RED}❌ 未能从订阅链接获取到任何有效节点，跳过此文件测速。{Style.RESET_ALL}")
        if invalid_sub_urls:
            new_path = _archive_file(target_file, "订阅全失效")
            if new_path:
                print(f"{Fore.YELLOW}📂 全部订阅均失效，文件已移入 Old_file: {os.path.basename(new_path)}{Style.RESET_ALL}")
                get_logger().log_node_test(os.path.basename(target_file), 0, 0, deleted=True)
                return
        get_logger().log_node_test(os.path.basename(target_file), 0, 0, deleted=False)
        return

    with open(target_file, 'r', encoding='utf-8', errors='ignore') as _f:
        _total_links = len(set(re.findall(r'https?://[^\s<>"]+', _f.read())))
    _valid_count = _total_links - len(invalid_sub_urls)
    print(
        f"{Fore.GREEN}\n✅ 订阅检测完成：{_valid_count} 个有效订阅 / {_total_links} 个总订阅，"
        f"共 {len(final_nodes)} 个节点（URL 模式不做节点测速）{Style.RESET_ALL}"
    )
    get_logger().log_sub_check(os.path.basename(target_file), _total_links, _valid_count)

    # 清理失效订阅 URL
    if invalid_sub_urls and os.path.exists(target_file):
        print(f"\n{Fore.YELLOW}🔗 预检发现 {len(invalid_sub_urls)} 个失效订阅 URL。{Style.RESET_ALL}")
        do_clean = (sub_clean_policy == 'yes')  # #1 修复：正确由参数推导 do_clean
        if do_clean:
            try:
                with open(target_file, 'r', encoding='utf-8', errors='ignore') as f:
                    raw_lines = f.readlines()
                new_lines = [l for l in raw_lines if not any(bad in l for bad in invalid_sub_urls)]
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                print(f"{Fore.GREEN}✅ 已从文件中移除 {len(invalid_sub_urls)} 个失效订阅 URL。{Style.RESET_ALL}")
                if not ''.join(new_lines).strip():
                    print(f"{Fore.YELLOW}⚠️  清理后文件已空，自动归档...{Style.RESET_ALL}")
                    _archive_file(target_file, "订阅全清空")
            except OSError as e:
                print(f"{Fore.RED}❌ 清除失败: {e}{Style.RESET_ALL}")
        else:
            print("已取消，订阅 URL 保持不变。")

    # 导出有效订阅为 TXT
    if valid_sub_urls:
        try:
            txt_dir   = Path(_cfg.BASE_DIR) / _cfg.TXT_FOLDER
            txt_dir.mkdir(parents=True, exist_ok=True)
            base_name = Path(target_file).stem
            now_tag   = _dt.now().strftime('%Y%m%d_%H%M%S')
            txt_out   = txt_dir / f"{base_name}_可用订阅_{now_tag}.txt"
            with open(txt_out, 'w', encoding='utf-8') as _f:
                _f.write('\n'.join(valid_sub_urls) + '\n')
            print(f"\n{Fore.GREEN}📝 可用订阅链接汇总已保存至:{Style.RESET_ALL}\n-> {txt_out}")
            print(f"   共 {len(valid_sub_urls)} 个可用订阅链接")
        except OSError as e:
            print(f"{Fore.YELLOW}⚠️  订阅链接汇总 TXT 生成失败: {e}{Style.RESET_ALL}")



@dataclass
class _NodeTestContext:
    target_file:  str
    final_nodes:  list
    ext:          str
    clean_policy: str
    export_policy: str
    engine:       BaseTestEngine
    batch_summary: list
    proxy_top_n:  int
    timeout_ms:   int
    test_url:     str
    test_session: aiohttp.ClientSession
    status_callback: callable = None # 增加回调


async def _process_single_file(ctx: _NodeTestContext) -> None:
    """
    核心测速流程：加载 Mihomo → 并发测试 → 展示 TOP N → 导出 YAML → 清理无效节点。
    结果追加到 ctx.batch_summary。
    """
    # (tqdm 已在文件顶部导入)
    # (datetime 已在文件顶部导入为 _dt)

    # 展开 ctx 属性到局部变量，保持后续逻辑不变
    target_file   = ctx.target_file
    final_nodes   = ctx.final_nodes
    ext           = ctx.ext
    clean_policy  = ctx.clean_policy
    export_policy = ctx.export_policy
    engine        = ctx.engine
    batch_summary = ctx.batch_summary
    proxy_top_n   = ctx.proxy_top_n

    print(f"  [阶段] 节点准备完成，共 {len(final_nodes)} 个，正在加载 {engine.engine_name} 内核配置...")
    if not await engine.start(final_nodes, _cfg.API_PORT, ctx.test_session):
        print(f"{Fore.RED}❌ {engine.engine_name} 内核启动超时/失败！跳过此文件。{Style.RESET_ALL}")
        return

    _timeout_ms = ctx.timeout_ms
    _test_url   = ctx.test_url
    print(f"{Fore.CYAN}  [阶段] 多线程外网测试 (URL: {_test_url}){Style.RESET_ALL}")
    print("-" * 60)

    results: list = []
    valid_results: list = []
    invalid_names: list = []
    verbose_log = bool(getattr(_cfg, "NODE_TEST_VERBOSE", False))

    _results = []
    sem = asyncio.Semaphore(_cfg.NODE_TEST_WORKERS)
    tasks = [asyncio.create_task(engine.async_test_node(n["name"], _timeout_ms, _test_url, ctx.test_session, sem)) for n in final_nodes]

    processed = 0
    total_nodes = len(final_nodes)

    for future in asyncio.as_completed(tasks):
        res = await future
        _results.append(res)
        processed += 1
        
        if res.get("status") == "valid" and res.get("delay", -1) > 0:
            valid_results.append(res)
        else:
            invalid_names.append(res['name'])

        if ctx.status_callback and (processed % 5 == 0 or processed == total_nodes):
            await ctx.status_callback(f"⏳ 正在测试: {processed}/{total_nodes}...")


    results = _results

    valid_names = {r["name"] for r in valid_results}
    print("-" * 60)
    print(
        f"📊 测速结果摘要: 总节点 {len(results)} 个 | "
        f"{Fore.GREEN}✅ 有效接通 {len(valid_results)} 个{Style.RESET_ALL} | "
        f"{Fore.RED}❌ 无效连接 {len(invalid_names)} 个{Style.RESET_ALL}"
    )

    # 导出通过节点为 YAML
    if valid_results:
        # Node tester shouldn't strictly handle inputs if policy is well defined
        do_export = export_policy == 'yes'
        print("💾 使用导出策略：" + ("自动导出" if do_export else "不导出"))
        if do_export:
            try:
                survived = [n for n in final_nodes if n["name"] in valid_names]
                yaml_dir = Path(_cfg.BASE_DIR) / _cfg.YAML_FOLDER
                yaml_dir.mkdir(parents=True, exist_ok=True)
                base     = Path(target_file).stem
                out_path = yaml_dir / f"{base}_通过_{_dt.now().strftime('%Y%m%d_%H%M%S')}.yaml"
                with open(out_path, 'w', encoding='utf-8') as ef:
                    yaml.dump({'proxies': survived}, ef, allow_unicode=True, sort_keys=False)
                print(f"{Fore.GREEN}✅ 已导出 {len(survived)} 个节点 → {out_path}{Style.RESET_ALL}")
            except OSError as e:
                print(f"{Fore.YELLOW}⚠️  导出失败: {e}{Style.RESET_ALL}")

    # 清理 / 归档逻辑
    fname = os.path.basename(target_file)
    total = len(results)

    if len(valid_results) == 0:
        print(f"{Fore.RED}⚠️  所有节点均无法连通，文件将被移入 Old_file 目录...{Style.RESET_ALL}")
        new_path = _archive_file(target_file, "全节点失效")
        if new_path:
            print(f"{Fore.YELLOW}📂 已归档: {os.path.basename(new_path)}{Style.RESET_ALL}")
            get_logger().log_node_test(fname, total, 0, deleted=True)
            batch_summary.append({'file': fname, 'total': total, 'valid': 0, 'status': '全失效归档'})
        else:
            get_logger().log_node_test(fname, total, 0, deleted=False)
            batch_summary.append({'file': fname, 'total': total, 'valid': 0, 'status': '全失效'})
        return

    if not invalid_names:
        print(f"{Fore.GREEN}🎉 太棒了！该文件内所有节点均连通外网。{Style.RESET_ALL}")
        get_logger().log_node_test(fname, total, len(valid_results))
        batch_summary.append({'file': fname, 'total': total, 'valid': len(valid_results), 'status': '全通过'})
        return

    # 有部分无效节点：询问是否清理
    if clean_policy == 'yes':
        print(f"\n🧹 自动清理策略: 移除 {len(invalid_names)} 个无效节点...")
        do_clean = True
    else:
        print("ℹ️  自动保留策略: 文件保持原样。")
        do_clean = False

    if do_clean:
        print(f"{Fore.CYAN}正在执行精准移除...{Style.RESET_ALL}")
        try:
            survived = [n for n in final_nodes if n["name"] in valid_names]
            if ext in ('.yaml', '.yml'):
                try:
                    with open(target_file, 'r', encoding='utf-8') as rf:
                        orig = yaml.safe_load(rf) or {}
                except (OSError, yaml.YAMLError):
                    orig = {}
                orig['proxies'] = survived
                with open(target_file, 'w', encoding='utf-8') as wf:
                    yaml.dump(orig, wf, allow_unicode=True, sort_keys=False)
            else:
                conv = SSNodeConverter()
                conv.nodes = survived
                conv.to_txt(target_file)
            print(f"{Fore.GREEN}✅ 成功移除了无效节点，保留 {len(survived)} 个已验证节点！{Style.RESET_ALL}")
            get_logger().log_node_test(fname, total, len(survived))
            batch_summary.append({'file': fname, 'total': total, 'valid': len(survived), 'status': '已清理'})
        except (OSError, ValueError) as e:
            print(f"{Fore.RED}❌ 清理时出错: {e}{Style.RESET_ALL}")
            get_logger().log_node_test(fname, total, len(valid_results))
            batch_summary.append({'file': fname, 'total': total, 'valid': len(valid_results), 'status': '清理出错'})
    else:
        print("已取消清理，文件保持原样。")
        get_logger().log_node_test(fname, total, len(valid_results))
        batch_summary.append({'file': fname, 'total': total, 'valid': len(valid_results), 'status': '保持原样'})
def run_node_latency_test(target_files, mode: str = 'auto', clean_policy: str = 'no', export_policy: str = 'no', sub_clean_policy: str = 'no', status_callback=None) -> None:
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_async_run_node_latency_test(target_files, mode, clean_policy, export_policy, sub_clean_policy, status_callback))
        finally:
            loop.close()
    else:
        asyncio.run(_async_run_node_latency_test(target_files, mode, clean_policy, export_policy, sub_clean_policy, status_callback))

async def _async_run_node_latency_test(target_files, mode: str = 'auto', clean_policy: str = 'no', export_policy: str = 'no', sub_clean_policy: str = 'no', status_callback=None) -> None:
    """
    执行真实节点连通性测试（Mihomo 进程复用版，异步全联通）。
    """
    importlib.reload(_cfg)
    proxy_top_n = _cfg.PROXY_TOP_N
    verbose_log = bool(getattr(_cfg, "NODE_TEST_VERBOSE", False))
    batch_summary: list = []

    print("=" * 60)
    print(f"{Fore.YELLOW}🚀 正在准备基于测速引擎的真实外网测速环境...{Style.RESET_ALL}")
    
    engine = MihomoEngine()
    if not await engine.prepare():
        return

    if isinstance(target_files, str):
        target_files = [target_files]

    # 检测文件类型，预设批量策略
    direct_files = [
        f for f in target_files
        if mode == 'direct' or (mode == 'auto' and auto_detect_file_mode(f) == 'direct')
    ]
    url_files = [
        f for f in target_files
        if mode == 'url' or (mode == 'auto' and auto_detect_file_mode(f) == 'url')
    ]

    clean_policy = 'no' if clean_policy in ('ask', None) else clean_policy
    export_policy = 'no' if export_policy in ('ask', None) else export_policy
    sub_clean_policy = 'no' if sub_clean_policy in ('ask', None) else sub_clean_policy

    sub_conn = aiohttp.TCPConnector(ssl=_cfg.VERIFY_SSL, limit=_cfg.get("SUB_DOWNLOAD_WORKERS", 30))
    sub_timeout = aiohttp.ClientTimeout(total=_cfg.get("SUB_TIMEOUT", 12))
    test_conn = aiohttp.TCPConnector(ssl=_cfg.VERIFY_SSL, limit=_cfg.NODE_TEST_WORKERS)
    test_timeout = aiohttp.ClientTimeout(total=max(30, _cfg.TIMEOUT_MS / 1000 + 10))

    try:
        async with aiohttp.ClientSession(connector=sub_conn, timeout=sub_timeout) as sub_session, \
                   aiohttp.ClientSession(connector=test_conn, timeout=test_timeout) as test_session:
            for target_file in target_files:
                print(f"\n{Fore.GREEN}📂 ====== 正在处理文件: {os.path.basename(target_file)} ======{Style.RESET_ALL}")
                file_mode  = mode if mode != 'auto' else auto_detect_file_mode(target_file)
                mode_label = "🔗 直接节点" if file_mode == 'direct' else "🌐 订阅URL"
                print(f"  🔍 自动识别文件内容: {Fore.CYAN}{mode_label}{Style.RESET_ALL}")

                if file_mode == 'url':
                    await _handle_url_file(target_file, sub_session, sub_clean_policy, batch_summary)
                    continue

                ext = os.path.splitext(target_file)[1].lower()
                converter = SSNodeConverter()
                ok = (
                    converter.parse_txt_file(target_file)  if ext == '.txt'  else
                    converter.parse_yaml_file(target_file) if ext in ('.yaml', '.yml') else False
                )
                if not ok or not converter.nodes:
                    print(f"{Fore.RED}❌ 未从文件中解析到有效的 Vmess/SS/Trojan 节点{Style.RESET_ALL}")
                    new_path = archive_to_old_file(target_file, "无法解析")
                    if new_path:
                        print(f"{Fore.YELLOW}📂 文件已移入 Old_file: {os.path.basename(new_path)}{Style.RESET_ALL}")
                        get_logger().log_node_test(os.path.basename(target_file), 0, 0, deleted=True)
                    else:
                        get_logger().log_node_test(os.path.basename(target_file), 0, 0, deleted=False)
                    continue

                final_nodes = _dedup_and_rename(converter.nodes)
                await _process_single_file(_NodeTestContext(
                    target_file=target_file,
                    final_nodes=final_nodes,
                    ext=ext,
                    clean_policy=clean_policy,
                    export_policy=export_policy,
                    engine=engine,
                    batch_summary=batch_summary,
                    proxy_top_n=_cfg.PROXY_TOP_N,
                    timeout_ms=_cfg.TIMEOUT_MS,
                    test_url=_cfg.TEST_URL,
                    test_session=test_session,
                    status_callback=status_callback # 传递给 ctx
                ))

    finally:
        engine.stop()
        _print_batch_summary(batch_summary)

    print(f"\n{Fore.GREEN}{Style.BRIGHT}✅ 所选的所有文件均已处理完毕。{Style.RESET_ALL}")
    gc.collect()

