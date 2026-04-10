"""
Project feature flags and runtime configuration.

All options can be overridden through environment variables in `.env`.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    """Read a boolean value from environment variables."""
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ============================================================
# Server profile presets (base defaults, can be overridden below)
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
# Feature flags (explicit env vars take precedence over profile)
# ============================================================
ENABLE_LATENCY_TESTER: bool = _bool("ENABLE_LATENCY_TESTER", _profile["latency_tester"])
ENABLE_MONITOR: bool = _bool("ENABLE_MONITOR", _profile["monitor"])
ENABLE_GEO_LOOKUP: bool = _bool("ENABLE_GEO_LOOKUP", _profile["geo_lookup"])
VERIFY_SSL: bool = _bool("VERIFY_SSL", True)
ENABLE_OWNER_LEGACY_READ_COMMANDS: bool = _bool("ENABLE_OWNER_LEGACY_READ_COMMANDS", True)
ENABLE_USER_COMPACT_SUB_BUTTONS: bool = _bool("ENABLE_USER_COMPACT_SUB_BUTTONS", True)

# Owner ID (highest admin permission)
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))


# ============================================================
# Performance settings
# ============================================================
URL_CACHE_MAX_SIZE: int = int(os.getenv("URL_CACHE_MAX_SIZE", "5000"))
URL_CACHE_TTL_SECONDS: int = int(os.getenv("URL_CACHE_TTL_SECONDS", "86400"))
LATENCY_TEST_CONCURRENCY: int = int(os.getenv("LATENCY_TEST_CONCURRENCY", str(_profile["concurrency"])))
GEO_LOOKUP_MAX_WORKERS: int = int(os.getenv("GEO_LOOKUP_MAX_WORKERS", "8"))
MAX_NODES_PER_PARSE: int = int(os.getenv("MAX_NODES_PER_PARSE", str(_profile["parse_limit"])))
MAX_GEO_QUERIES: int = int(os.getenv("MAX_GEO_QUERIES", "50"))
PARSE_GLOBAL_CONCURRENCY: int = int(os.getenv("PARSE_GLOBAL_CONCURRENCY", "24"))
PARSE_USER_CONCURRENCY: int = int(os.getenv("PARSE_USER_CONCURRENCY", "6"))
PARSE_SLOW_THRESHOLD_SECONDS: float = float(os.getenv("PARSE_SLOW_THRESHOLD_SECONDS", "8"))
PARSE_STATS_REPORT_EVERY: int = int(os.getenv("PARSE_STATS_REPORT_EVERY", "50"))
PARSE_SUCCESS_CACHE_TTL_SECONDS: int = int(os.getenv("PARSE_SUCCESS_CACHE_TTL_SECONDS", "12"))
PARSE_SUCCESS_CACHE_MAX_SIZE: int = int(os.getenv("PARSE_SUCCESS_CACHE_MAX_SIZE", "512"))


def print_config_summary():
    """Print current runtime config summary at startup."""
    import logging

    logger = logging.getLogger("config")

    def _flag(value: bool) -> str:
        return "ENABLED" if value else "DISABLED"

    logger.info("=" * 50)
    logger.info("Configuration Summary")
    logger.info(f"Server profile: {SERVER_PROFILE.upper()}")
    logger.info(f"Latency tester: {_flag(ENABLE_LATENCY_TESTER)}")
    logger.info(f"Monitor scheduler: {_flag(ENABLE_MONITOR)}")
    logger.info(f"Geo lookup: {_flag(ENABLE_GEO_LOOKUP)}")
    logger.info(f"Owner legacy read commands: {_flag(ENABLE_OWNER_LEGACY_READ_COMMANDS)}")
    logger.info(f"User compact sub-buttons: {_flag(ENABLE_USER_COMPACT_SUB_BUTTONS)}")
    logger.info(f"SSL verification: {_flag(VERIFY_SSL)}")
    logger.info(f"Max nodes per parse: {MAX_NODES_PER_PARSE}")
    logger.info(f"Global parse concurrency: {PARSE_GLOBAL_CONCURRENCY}")
    logger.info(f"Per-user parse concurrency: {PARSE_USER_CONCURRENCY}")
    logger.info(f"Slow parse threshold(s): {PARSE_SLOW_THRESHOLD_SECONDS}")
    logger.info(f"Parse stats report every: {PARSE_STATS_REPORT_EVERY}")
    logger.info(f"Parse success cache TTL(s): {PARSE_SUCCESS_CACHE_TTL_SECONDS}")
    logger.info(f"URL cache size limit: {URL_CACHE_MAX_SIZE}")
    logger.info("=" * 50)


# ============================================================
# Latency tester configuration
# ============================================================
TIMEOUT_MS: int = int(os.getenv("TIMEOUT_MS", "6000"))
API_PORT: int = int(os.getenv("API_PORT", "19090"))
TEST_URL: str = os.getenv("TEST_URL", "http://www.gstatic.com/generate_204")
NODE_TEST_WORKERS: int = LATENCY_TEST_CONCURRENCY
PROXY_TOP_N: int = int(os.getenv("PROXY_TOP_N", "10"))

# Subscription parsing optimization settings
SUB_TIMEOUT: int = int(os.getenv("SUB_TIMEOUT", str(_profile["timeout"])))
SUB_DOWNLOAD_WORKERS: int = int(os.getenv("SUB_DOWNLOAD_WORKERS", "30"))
UA_CLASH: str = "ClashForAndroid/2.5.12"

LOG_KEEP_DAYS: int = int(os.getenv("LOG_KEEP_DAYS", "30"))
NODE_TEST_VERBOSE: bool = _bool("NODE_TEST_VERBOSE", False)

# Base directory settings
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TXT_FOLDER = "data/txt_workspace"
YAML_FOLDER = "data/yaml_workspace"
OLD_FILE_DIR_NAME = "data/archives"
LOG_DIR_NAME = "logs"
