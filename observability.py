"""Adolf-StreamX observability and request-rate limiting helpers."""
import threading
import time
from fastapi.responses import JSONResponse
from config import REQUEST_RATE_LIMIT, REQUEST_RATE_WINDOW, MAX_RATE_LIMIT_KEYS

server_metrics = {"requests": 0, "rate_limited": 0, "streams_started": 0, "streams_completed": 0, "streams_failed": 0, "stream_disconnects": 0, "telegram_retries": 0, "telegram_floodwaits": 0, "db_failures": 0, "cache_hits": 0, "cache_misses": 0, "prefetch_started": 0, "prefetch_completed": 0, "pair_invalid": 0, "pair_locked": 0}
metrics_lock = threading.Lock()
request_rate_state = {}
request_rate_lock = threading.Lock()

def metric_inc(name, amount=1):
    with metrics_lock:
        server_metrics[name] = server_metrics.get(name, 0) + amount

def get_metrics_snapshot():
    with metrics_lock:
        return dict(server_metrics)

def cleanup_request_rate_state():
    cutoff = time.monotonic() - REQUEST_RATE_WINDOW
    with request_rate_lock:
        for client, state in list(request_rate_state.items()):
            if state[0] < cutoff:
                request_rate_state.pop(client, None)

async def request_rate_middleware(request, call_next):
    path = request.url.path
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    if path not in ("/", "/health", "/metrics"):
        with request_rate_lock:
            state = request_rate_state.get(client)
            if state is None or now - state[0] >= REQUEST_RATE_WINDOW:
                request_rate_state[client] = [now, 1]
            else:
                state[1] += 1
                if state[1] > REQUEST_RATE_LIMIT:
                    metric_inc("rate_limited")
                    return JSONResponse({"ok": False, "error": "Too many requests", "retry_after": REQUEST_RATE_WINDOW}, status_code=429, headers={"Retry-After": str(REQUEST_RATE_WINDOW)})
            if len(request_rate_state) > MAX_RATE_LIMIT_KEYS:
                for key, _ in sorted(request_rate_state.items(), key=lambda item: item[1][0])[:max(1, len(request_rate_state)//10)]:
                    request_rate_state.pop(key, None)
    metric_inc("requests")
    return await call_next(request)
