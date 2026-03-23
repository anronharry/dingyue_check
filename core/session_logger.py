#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话日志记录模块
记录每次运行中的检测操作摘要，并在会话结束时输出/保存汇总日志
"""

import os
from datetime import datetime, timedelta
from colorama import Fore, Style, init
import config as _cfg

init(autoreset=True)

# 日志保存在与主程序同级的 logs/ 子目录下
_BASE_DIR = str(_cfg.BASE_DIR)
LOG_DIR = os.path.join(_BASE_DIR, _cfg.LOG_DIR_NAME)
LOG_FILE_PREFIX = "运行日志"
os.makedirs(LOG_DIR, exist_ok=True)  # 首次运行时自动创建日志目录


class SessionLogger:
    """会话日志管理器，记录本次运行中所有操作的汇总信息"""
    
    def __init__(self):
        self.session_start = datetime.now()
        # 每条记录格式: {'type': 'node_test'|'sub_check', 'file': str, 'total': int, 'survived': int, 'detail': str}
        self.records = []
    
    def log_node_test(self, filename: str, total_nodes: int, survived_nodes: int, deleted: bool = False):
        """
        记录一次节点真实连通性测速的结果
        
        Args:
            filename: 被检测的文件名
            total_nodes: 提取到的总节点数
            survived_nodes: 测速通过的节点数
            deleted: 文件是否已被删除（全无效时）
        """
        detail = f"已自动归档（全部节点失效）" if deleted else f"幸存节点: {survived_nodes}/{total_nodes}"
        self.records.append({
            'type': 'node_test',
            'file': filename,
            'total': total_nodes,
            'survived': survived_nodes,
            'deleted': deleted,
            'detail': detail,
            'time': datetime.now().strftime('%H:%M:%S')
        })
    
    def log_sub_check(self, filename: str, total_links: int, valid_links: int, deleted: bool = False):
        """
        记录一次订阅地址有效性检测的结果
        
        Args:
            filename: 被检测的文件名
            total_links: 提取到的总链接数
            valid_links: 有效链接数
            deleted: 文件是否已被删除
        """
        detail = f"已自动归档（无有效链接）" if deleted else f"有效链接: {valid_links}/{total_links}"
        self.records.append({
            'type': 'sub_check',
            'file': filename,
            'total': total_links,
            'survived': valid_links,
            'deleted': deleted,
            'detail': detail,
            'time': datetime.now().strftime('%H:%M:%S')
        })
        
    # --- 增加全局统一管控的带色彩日志打印函数 ---
    @staticmethod
    def print_info(msg: str):
        print(f"{Fore.CYAN}ℹ️  {msg}{Style.RESET_ALL}")
        
    @staticmethod
    def print_success(msg: str):
        print(f"{Fore.GREEN}✅ {msg}{Style.RESET_ALL}")

    @staticmethod
    def print_warning(msg: str):
        print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}")

    @staticmethod
    def print_error(msg: str):
        print(f"{Fore.RED}❌ {msg}{Style.RESET_ALL}")

    def print_session_summary(self):
        """在控制台输出本次会话的汇总日志（仿照 check_sub.py 风格）"""
        if not self.records:
            return
        
        session_end = datetime.now()
        duration = (session_end - self.session_start).total_seconds()
        
        print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}{'✅ 本次会话运行日志汇总':^56}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}🕐 会话开始:{Style.RESET_ALL} {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  {Fore.YELLOW}🕑 会话结束:{Style.RESET_ALL} {session_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  {Fore.YELLOW}⏱️  总耗时:{Style.RESET_ALL} {duration:.1f} 秒")
        print(f"  {Fore.BLUE}📊 总共执行:{Style.RESET_ALL} {len(self.records)} 项操作")
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        
        node_test_count = 0
        sub_check_count = 0
        
        for idx, rec in enumerate(self.records, 1):
            if rec['type'] == 'node_test':
                node_test_count += 1
                icon = "⚡"
                type_str = "节点测速"
            else:
                sub_check_count += 1
                icon = "🌐"
                type_str = "订阅检测"
            
            survived = rec['survived']
            total = rec['total']
            
            if rec.get('deleted'):
                color = Fore.RED
            elif total == 0 or survived == 0:
                color = Fore.RED
            elif survived / total >= 0.5:
                color = Fore.GREEN
            else:
                color = Fore.YELLOW
            
            print(f"  [{idx:02d}] {icon} [{type_str}] [{rec['time']}] {rec['file']}")
            print(f"        {color}{rec['detail']}{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}{'-'*60}{Style.RESET_ALL}")
        if node_test_count:
            print(f"  ⚡ 节点测速: 共 {node_test_count} 次")
        if sub_check_count:
            print(f"  🌐 订阅检测: 共 {sub_check_count} 次")
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        
        # 保存日志到文件
        self._save_log_file(session_end, duration, node_test_count, sub_check_count)
        # 自动清理过期日志
        self._auto_clean_old_logs()
    
    def _save_log_file(self, session_end: datetime, duration: float, node_count: int, sub_count: int):
        """将会话日志保存为精美排版的文本文件"""
        try:
            today_str = self.session_start.strftime('%Y-%m-%d')
            log_filename = os.path.join(LOG_DIR, f"{LOG_FILE_PREFIX}_{today_str}.log")
            
            # 追加模式，便于同一天多次运行都能记录
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"{'会话运行日志汇总':^56}\n")
                f.write("=" * 60 + "\n")
                f.write(f"会话开始: {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"会话结束: {session_end.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总耗时: {duration:.1f} 秒\n")
                f.write(f"共执行操作: {len(self.records)} 项\n")
                f.write("=" * 60 + "\n\n")
                
                f.write(f"📊 统计摘要\n")
                f.write("-" * 60 + "\n")
                if node_count:
                    f.write(f"  ⚡ 节点测速: {node_count} 次\n")
                if sub_count:
                    f.write(f"  🌐 订阅检测: {sub_count} 次\n")
                f.write("-" * 60 + "\n\n")

                f.write(f"✨ 操作详情记录\n")
                f.write("=" * 60 + "\n")
                for idx, rec in enumerate(self.records, 1):
                    icon = "⚡" if rec['type'] == 'node_test' else "🌐"
                    type_str = "节点测速" if rec['type'] == 'node_test' else "订阅检测"
                    status_icon = "❌" if rec.get('deleted') or rec['survived'] == 0 else "✅" if rec['survived'] / max(1, rec['total']) > 0.5 else "⚠️"
                    f.write(f"[{idx:02d}] {icon} [{type_str}] [{rec['time']}] 文件: {rec['file']}\n")
                    f.write(f"     {status_icon} {rec['detail']}\n")
                
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"{'报告生成完毕':^56}\n")
                f.write("=" * 60 + "\n")
            
            print(f"\n{Fore.GREEN}📝 会话日志已保存至: {log_filename}{Style.RESET_ALL}\n")
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  日志保存失败: {e}{Style.RESET_ALL}")

    def _auto_clean_old_logs(self):
        """自动清理超过 LOG_KEEP_DAYS 天的旧日志文件，0 表示不清理"""
        keep_days = int(getattr(_cfg, 'LOG_KEEP_DAYS', 0))
        if keep_days <= 0:
            return
        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = 0
        try:
            for fname in os.listdir(LOG_DIR):
                if not fname.endswith('.log'):
                    continue
                fpath = os.path.join(LOG_DIR, fname)
                try:
                    if datetime.fromtimestamp(os.path.getmtime(fpath)) < cutoff:
                        os.remove(fpath)
                        removed += 1
                except Exception:
                    pass
            if removed:
                print(f"{Fore.YELLOW}🗑️  已自动清理 {removed} 个超过 {keep_days} 天的旧日志文件{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  日志自动清理失败: {e}{Style.RESET_ALL}")


# 全局单例，供所有模块共享使用
_global_logger: SessionLogger = None


def get_logger() -> SessionLogger:
    """获取全局会话日志实例"""
    global _global_logger
    if _global_logger is None:
        _global_logger = SessionLogger()
    return _global_logger


def reset_logger():
    """重置全局日志实例（用于新会话开始时）"""
    global _global_logger
    _global_logger = SessionLogger()

from __future__ import annotations
