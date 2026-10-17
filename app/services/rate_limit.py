from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import ApplicationError


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class RateLimiter(Protocol):
    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult: ...


class RedisRateLimiter:
    _SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        try:
            count, ttl = await self._redis.eval(  # type: ignore[misc]
                self._SCRIPT,
                1,
                f"ekh:rate-limit:{key}",
                str(window_seconds),
            )
        except RedisError as exc:
            raise ApplicationError(
                "Rate limiting is temporarily unavailable",
                code="rate_limit_unavailable",
                status_code=503,
            ) from exc
        retry_after = max(int(ttl), 1)
        return RateLimitResult(int(count) <= limit, retry_after)
