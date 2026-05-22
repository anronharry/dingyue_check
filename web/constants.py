"""Shared constants and app keys for the web admin server."""

from __future__ import annotations

import os

from aiohttp import web


API_PREFIX = "/api/v1"
SESSION_COOKIE = "web_admin_session"
LOGIN_WINDOW_SECONDS = 600
MAX_LOGIN_ATTEMPTS = 5

RUNTIME_KEY = web.AppKey("runtime", object)
TOKEN_KEY = web.AppKey("web_admin_token", str)
USERNAME_KEY = web.AppKey("web_admin_username", str)
ALLOW_HEADER_TOKEN_KEY = web.AppKey("web_admin_allow_header_token", bool)
COOKIE_SECURE_KEY = web.AppKey("web_admin_cookie_secure", bool)
TRUST_PROXY_KEY = web.AppKey("web_admin_trust_proxy", bool)
LOGIN_WINDOW_KEY = web.AppKey("web_admin_login_window_seconds", int)
LOGIN_MAX_ATTEMPTS_KEY = web.AppKey("web_admin_login_max_attempts", int)
SESSION_TTL_KEY = web.AppKey("web_admin_session_ttl", int)
AUTH_BACKEND_KEY = web.AppKey("web_admin_auth_backend", object)
REDIS_ALLOW_MEMORY_FALLBACK_KEY = web.AppKey("web_admin_redis_allow_memory_fallback", bool)
STARTED_AT_KEY = web.AppKey("web_admin_started_at", float)
AGG_STATE_KEY = web.AppKey("owner_aggregate_state", object)
AGG_TASK_KEY = web.AppKey("owner_aggregate_task", object)
AGG_API_DEPS_KEY = web.AppKey("owner_aggregate_api_deps", object)

AGG_PARSE_CONCURRENCY = 6
AGG_PARSE_TIMEOUT_SECONDS = 15
AGG_NODE_TEST_TIMEOUT_SECONDS = float(os.getenv("OWNER_AGGREGATE_NODE_TEST_TIMEOUT_SECONDS", "1.5"))
AGG_NODE_TEST_CONCURRENCY = int(os.getenv("OWNER_AGGREGATE_NODE_TEST_CONCURRENCY", "40"))
AGG_NODE_SOURCE_LIMIT = int(os.getenv("OWNER_AGGREGATE_SOURCE_LIMIT", "24"))
AGG_NODE_CANDIDATE_LIMIT = int(os.getenv("OWNER_AGGREGATE_CANDIDATE_LIMIT", "180"))
AGG_NODE_PUBLISH_LIMIT = int(os.getenv("OWNER_AGGREGATE_PUBLISH_LIMIT", "120"))
AGG_NODE_QUICK_TTL_SECONDS = int(os.getenv("OWNER_AGGREGATE_NODE_QUICK_TTL_SECONDS", "1800"))
AGG_NODE_VERIFY_TTL_SECONDS = int(os.getenv("OWNER_AGGREGATE_NODE_VERIFY_TTL_SECONDS", "21600"))
AGG_NODE_VERIFY_ENABLED = str(
    os.getenv("OWNER_AGGREGATE_VERIFY_ENABLED", "1")
).strip().lower() not in {
    "0",
    "false",
    "no",
}
AGG_NODE_VERIFY_LIMIT = int(os.getenv("OWNER_AGGREGATE_VERIFY_LIMIT", "30"))
AGG_NODE_VERIFY_TIMEOUT_MS = int(os.getenv("OWNER_AGGREGATE_VERIFY_TIMEOUT_MS", "3500"))
AGG_NODE_STABLE_SUCCESS_THRESHOLD = int(os.getenv("OWNER_AGGREGATE_STABLE_SUCCESS_THRESHOLD", "2"))
AGG_NODE_EVICT_FAILURE_THRESHOLD = int(os.getenv("OWNER_AGGREGATE_EVICT_FAILURE_THRESHOLD", "2"))
AGG_PREWARM_INTERVAL_SECONDS = int(os.getenv("OWNER_AGGREGATE_PREWARM_INTERVAL_SECONDS", "180"))
AGG_HEALTH_SCORE_MIN = 0
AGG_HEALTH_SCORE_MAX = 100
AGG_STABLE_REVERIFY_LIMIT = int(os.getenv("OWNER_AGGREGATE_STABLE_REVERIFY_LIMIT", "12"))
AGG_PUBLISH_SOURCE_LIMIT = int(os.getenv("OWNER_AGGREGATE_PUBLISH_SOURCE_LIMIT", "12"))
AGG_PUBLISH_SERVER_LIMIT = int(os.getenv("OWNER_AGGREGATE_PUBLISH_SERVER_LIMIT", "3"))
AGG_PREWARM_MIN_SECONDS = int(os.getenv("OWNER_AGGREGATE_PREWARM_MIN_SECONDS", "60"))
AGG_PREWARM_MAX_SECONDS = int(os.getenv("OWNER_AGGREGATE_PREWARM_MAX_SECONDS", "300"))
AGG_POOL_STABLE_RATIO = int(os.getenv("OWNER_AGGREGATE_POOL_STABLE_RATIO", "70"))
AGG_POOL_WARM_RATIO = int(os.getenv("OWNER_AGGREGATE_POOL_WARM_RATIO", "20"))
AGG_POOL_FRESH_RATIO = int(os.getenv("OWNER_AGGREGATE_POOL_FRESH_RATIO", "10"))
AGG_HEALTH_DECAY_WINDOW_SECONDS = int(
    os.getenv("OWNER_AGGREGATE_HEALTH_DECAY_WINDOW_SECONDS", "21600")
)
