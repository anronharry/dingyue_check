"""
项目功能开关配置。

通过修改下方的 True / False 控制各模块的启用状态。
也可以通过 .env 文件覆盖这里的默认值，.env 优先级更高。
"""


from __future__ import annotations
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    """从环境变量读取布尔值，未配置时使用代码默认值。"""
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ============================================================
# 服务器档位预设（快速选择，会被下方单项开关覆盖）
# ============================================================
_profile_env = os.getenv("SERVER_PROFILE", "").strip().lower()
if _profile_env in ("256mb", "512mb", "1gb"):
    SERVER_PROFILE = _profile_env
else:
    SERVER_PROFILE = "1gb"
    # SERVER_PROFILE = "512mb"
    # SERVER_PROFILE = "256mb"

_defaults = {
    "256mb": dict(latency_tester=False, monitor=True, geo_lookup=False, concurrency=10, timeout=10, parse_limit=150),
    "512mb": dict(latency_tester=True, monitor=True, geo_lookup=True, concurrency=25, timeout=12, parse_limit=300),
    "1gb": dict(latency_tester=True, monitor=True, geo_lookup=True, concurrency=50, timeout=15, parse_limit=500),
}
_profile = _defaults.get(SERVER_PROFILE, _defaults["1gb"])


# ============================================================
# 功能开关（单独配置优先于 SERVER_PROFILE）
# ============================================================
ENABLE_LATENCY_TESTER: bool = _bool("ENABLE_LATENCY_TESTER", _profile["latency_tester"])
ENABLE_MONITOR: bool = _bool("ENABLE_MONITOR", _profile["monitor"])
ENABLE_GEO_LOOKUP: bool = _bool("ENABLE_GEO_LOOKUP", _profile["geo_lookup"])

# 所有者 (Owner) ID，拥有最高管理权限
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))


# ============================================================
# 性能参数（可按服务器规格调整）
# ============================================================
URL_CACHE_MAX_SIZE: int = int(os.getenv("URL_CACHE_MAX_SIZE", "5000"))
URL_CACHE_TTL_SECONDS: int = int(os.getenv("URL_CACHE_TTL_SECONDS", "86400"))
LATENCY_TEST_CONCURRENCY: int = int(os.getenv("LATENCY_TEST_CONCURRENCY", str(_profile["concurrency"])))
GEO_LOOKUP_MAX_WORKERS: int = int(os.getenv("GEO_LOOKUP_MAX_WORKERS", "8"))
MAX_NODES_PER_PARSE: int = int(os.getenv("MAX_NODES_PER_PARSE", str(_profile["parse_limit"])))
MAX_GEO_QUERIES: int = int(os.getenv("MAX_GEO_QUERIES", "50"))


def print_config_summary():
    """启动时打印当前功能开关状态。"""
    import logging

    logger = logging.getLogger("config")

    def _flag(value: bool) -> str:
        return "已开启" if value else "已关闭"

    logger.info("=" * 50)
    logger.info("当前配置摘要")
    logger.info(f"服务器档位: {SERVER_PROFILE.upper()}")
    logger.info(f"节点测速: {_flag(ENABLE_LATENCY_TESTER)}")
    logger.info(f"定时监控告警: {_flag(ENABLE_MONITOR)}")
    logger.info(f"真实 IP 查询: {_flag(ENABLE_GEO_LOOKUP)}")
    logger.info(f"单次解析节点上限: {MAX_NODES_PER_PARSE}")
    logger.info(f"URL 缓存上限: {URL_CACHE_MAX_SIZE}")
    logger.info("=" * 50)


# ============================================================
# 测速引擎配置
# ============================================================
TIMEOUT_MS: int = int(os.getenv("TIMEOUT_MS", "6000"))
API_PORT: int = int(os.getenv("API_PORT", "19090"))
TEST_URL: str = os.getenv("TEST_URL", "http://www.gstatic.com/generate_204")
NODE_TEST_WORKERS: int = LATENCY_TEST_CONCURRENCY
PROXY_TOP_N: int = int(os.getenv("PROXY_TOP_N", "10"))

# 订阅解析优化设置
SUB_TIMEOUT: int = int(os.getenv("SUB_TIMEOUT", str(_profile["timeout"])))
SUB_DOWNLOAD_WORKERS: int = int(os.getenv("SUB_DOWNLOAD_WORKERS", "30"))
UA_CLASH: str = "ClashForAndroid/2.5.12"

LOG_KEEP_DAYS: int = int(os.getenv("LOG_KEEP_DAYS", "30"))
NODE_TEST_VERBOSE: bool = _bool("NODE_TEST_VERBOSE", False)

# 基础目录配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TXT_FOLDER = "data/txt_workspace"
YAML_FOLDER = "data/yaml_workspace"
OLD_FILE_DIR_NAME = "data/archives"
LOG_DIR_NAME = "logs"
