"""
guardrails.py — cheap safety rails so one abuser can't run up your API bill.

Right now this holds a simple in-memory rate limiter: it remembers, per visitor
(by IP address), the times of their recent requests, and blocks anyone who goes
over the limit.

"In-memory" means the counts live in this running program — they reset when the
server restarts, and aren't shared if you run several server processes. That's
perfectly fine for launch; swap in Redis if you ever scale to many servers.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# --- Settings: tweak these to taste -----------------------------------------
MAX_REQUESTS = 20      # how many messages one visitor may send...
WINDOW_SECONDS = 60    # ...within this many seconds

# ip -> timestamps of that IP's recent requests
_hits = defaultdict(deque)


def client_ip(request: Request):
    """Best guess at the visitor's IP, even when we're behind a host's proxy."""
    # When deployed, the real IP is usually in this header (the proxy adds it).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request):
    """Raise HTTP 429 if this IP has sent too many requests recently."""
    ip = client_ip(request)
    now = time.time()
    hits = _hits[ip]

    # Forget any requests older than the time window.
    while hits and hits[0] <= now - WINDOW_SECONDS:
        hits.popleft()

    if len(hits) >= MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many messages — please slow down and try again in a minute.",
        )

    hits.append(now)
