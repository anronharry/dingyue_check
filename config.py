"""
项目功能开关配置
通过修改下方的 True / False 控制各模块的启用状态

推荐配置参考：
  256MB 服务器 → 注释掉 ENABLE_VISUALIZER = True，改 False
  512MB 服务器 → 可开启除可视化外的全部功能
  1GB+ 服务器  → 全部 True，体验最完整

也可以通过 .env 文件覆盖这里的默认值，.env 优先级更高。
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    """从环境变量读取布尔值，未配置时使用代码默认值"""
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


# ============================================================
# 服务器档位预设（快速选择，会被下方单项开关覆盖）
# 将对应档位的注释取消即可，只保留一行生效
# ============================================================
_profile_env = os.getenv("SERVER_PROFILE", "").strip().lower()
if _profile_env in ("256mb", "512mb", "1gb"):
    SERVER_PROFILE = _profile_env          # 从环境变量指定
else:
    SERVER_PROFILE = "1gb"                 # 代码默认：1GB 完整模式
    # SERVER_PROFILE = "512mb"             # 取消注释切换标准模式
    # SERVER_PROFILE = "256mb"             # 取消注释切换极简模式

_defaults = {
    "256mb": dict(latency_tester=False, monitor=True,  geo_lookup=False, concurrency=10, timeout=10, parse_limit=150),
    "512mb": dict(latency_tester=True,  monitor=True,  geo_lookup=True,  concurrency=25, timeout=12, parse_limit=300),
    "1gb":   dict(latency_tester=True,  monitor=True,  geo_lookup=True,  concurrency=50, timeout=15, parse_limit=500),
}
_profile = _defaults.get(SERVER_PROFILE, _defaults["1gb"])


# ============================================================
# 功能开关（单独配置优先于 SERVER_PROFILE）
# ============================================================

# ⚡ 节点 TCP 测速
ENABLE_LATENCY_TESTER: bool = _bool("ENABLE_LATENCY_TESTER", _profile["latency_tester"])

# 🔔 后台定时监控与告警（每天 12:00 / 20:00 自动巡检）
ENABLE_MONITOR: bool = _bool("ENABLE_MONITOR", _profile["monitor"])

# 🌍 真实 IP 地理位置查询（调用 ip-api.com，有速率限制）
#    关闭后退回关键词匹配，精度略低但零网络开销
ENABLE_GEO_LOOKUP: bool = _bool("ENABLE_GEO_LOOKUP", _profile["geo_lookup"])

# 👑 所有者 (Owner) ID - 拥有最高管理权限
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

# ============================================================
# 性能参数（可按服务器规格调整）
# ============================================================

# URL 短链缓存最大条目数（每条约 100 bytes）
URL_CACHE_MAX_SIZE: int = int(os.getenv("URL_CACHE_MAX_SIZE", "5000"))

# URL 缓存 TTL（秒），默认 24 小时
URL_CACHE_TTL_SECONDS: int = int(os.getenv("URL_CACHE_TTL_SECONDS", "86400"))

# 节点测速最大并发数（内存小时适当降低）
LATENCY_TEST_CONCURRENCY: int = int(os.getenv("LATENCY_TEST_CONCURRENCY", str(_profile["concurrency"])))

# 地理位置查询最大并发线程数
GEO_LOOKUP_MAX_WORKERS: int = int(os.getenv("GEO_LOOKUP_MAX_WORKERS", "8"))

# 单次解析最多节点数（防 OOM）
MAX_NODES_PER_PARSE: int = int(os.getenv("MAX_NODES_PER_PARSE", str(_profile["parse_limit"])))

# 地理位置查询上限（ip-api.com 免费版限速 45 req/min）
MAX_GEO_QUERIES: int = int(os.getenv("MAX_GEO_QUERIES", "50"))


# ============================================================
# 状态打印（启动时输出当前配置，方便排查问题）
# ============================================================
def print_config_summary():
    """启动时打印当前功能开关状态"""
    import logging
    logger = logging.getLogger("config")

    def _flag(v: bool) -> str:
        return "✅ 开启" if v else "❌ 关闭"

    logger.info("=" * 50)
    logger.info(f"⚙️  当前服务器档位: {SERVER_PROFILE.upper()}")
    logger.info(f"   ⚡ 节点测速      : {_flag(ENABLE_LATENCY_TESTER)}")
    logger.info(f"   🔔 定时监控告警  : {_flag(ENABLE_MONITOR)}")
    logger.info(f"   🌍 真实IP查询    : {_flag(ENABLE_GEO_LOOKUP)}")
    logger.info(f"   📦 节点上限/次   : {MAX_NODES_PER_PARSE}")
    logger.info(f"   🔗 URL缓存上限   : {URL_CACHE_MAX_SIZE}")
    logger.info("=" * 50)
# ============================================================
# 测速引擎配置 (由 Jiedian 迁移)
# ============================================================

# 测速超时时间（毫秒）
TIMEOUT_MS: int = int(os.getenv("TIMEOUT_MS", "6000"))

# Mihomo 内核交互端口
API_PORT: int = int(os.getenv("API_PORT", "19090"))

# 测速目标 URL
TEST_URL: str = os.getenv("TEST_URL", "http://www.gstatic.com/generate_204")

# 测速并发线程数
NODE_TEST_WORKERS: int = LATENCY_TEST_CONCURRENCY

# 测速结果展示 TOP N
PROXY_TOP_N: int = int(os.getenv("PROXY_TOP_N", "10"))

# 订阅解析优化设置
SUB_TIMEOUT: int = int(os.getenv("SUB_TIMEOUT", str(_profile["timeout"])))
SUB_DOWNLOAD_WORKERS: int = int(os.getenv("SUB_DOWNLOAD_WORKERS", "30"))
UA_CLASH: str = "ClashForAndroid/2.5.12"

# 测速日志保留天数
LOG_KEEP_DAYS: int = int(os.getenv("LOG_KEEP_DAYS", "30"))

# 测速详情打印输出
NODE_TEST_VERBOSE: bool = _bool("NODE_TEST_VERBOSE", False)

# 基础目录配置 (给迁移引擎使用)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TXT_FOLDER = "data/txt_workspace"
YAML_FOLDER = "data/yaml_workspace"
OLD_FILE_DIR_NAME = "data/archives"
