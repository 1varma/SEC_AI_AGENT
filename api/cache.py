import json
import hashlib
import redis

# ─── Configuration ────────────────────────────────────────────────────────────
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB   = 0

# TTLs in seconds
TTL_FILING_QUERY = 86400    # 24 hours — filing data doesn't change
TTL_STOCK_QUERY  = 3600     # 1 hour   — stock data refreshes daily
TTL_NEWS_QUERY   = 1800     # 30 mins  — news is most time-sensitive
TTL_DEFAULT      = 3600     # 1 hour   — fallback

_client = None


def get_redis():
    global _client
    if _client is None:
        _client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=2
        )
    return _client


def is_available() -> bool:
    """Check if Redis is reachable. Returns False gracefully if not running."""
    try:
        get_redis().ping()
        return True
    except Exception:
        return False


def make_key(query: str) -> str:
    """Stable cache key from query string."""
    normalized = query.strip().lower()
    return f"finsight:query:{hashlib.sha256(normalized.encode()).hexdigest()}"


def infer_ttl(query: str) -> int:
    """Pick TTL based on query content."""
    q = query.lower()
    if any(w in q for w in ["news", "sentiment", "today", "recent", "latest news"]):
        return TTL_NEWS_QUERY
    if any(w in q for w in ["price", "stock", "close", "52w", "volume", "chart"]):
        return TTL_STOCK_QUERY
    return TTL_FILING_QUERY


def get_cached(query: str) -> dict | None:
    """Return cached response dict or None if not found."""
    if not is_available():
        return None
    try:
        key  = make_key(query)
        data = get_redis().get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


def set_cached(query: str, response: dict) -> None:
    """Cache a response dict with appropriate TTL."""
    if not is_available():
        return
    try:
        key = make_key(query)
        ttl = infer_ttl(query)
        get_redis().setex(key, ttl, json.dumps(response, default=str))
    except Exception:
        pass


def invalidate(query: str) -> None:
    """Remove a specific query from cache."""
    if not is_available():
        return
    try:
        get_redis().delete(make_key(query))
    except Exception:
        pass


def flush_all() -> None:
    """Clear entire FinSight cache (not all Redis keys)."""
    if not is_available():
        return
    try:
        r    = get_redis()
        keys = r.keys("finsight:query:*")
        if keys:
            r.delete(*keys)
    except Exception:
        pass
