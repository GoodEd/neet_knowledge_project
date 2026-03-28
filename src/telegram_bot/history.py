# pyright: reportMissingImports=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportAny=false

import json
import logging
import os
from urllib.parse import urlparse

import redis


logger = logging.getLogger(__name__)


class TelegramChatHistory:
    def __init__(self, redis_url=None, max_turns=4, ttl_seconds=604800):
        self._redis = None
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds

        effective_redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )

        def _build_client(url: str):
            return redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=False,
            )

        try:
            client = _build_client(effective_redis_url)
            client.ping()
            self._redis = client
            return
        except Exception:
            parsed = urlparse(effective_redis_url)
            if parsed.scheme == "redis":
                tls_url = effective_redis_url.replace("redis://", "rediss://", 1)
                try:
                    client = _build_client(tls_url)
                    client.ping()
                    self._redis = client
                    return
                except Exception:
                    logger.exception("Telegram history: Redis TLS retry failed")

            logger.exception("Telegram history: Redis connection failed")

    def _key(self, user_id: int) -> str:
        return f"telegram_chat:{user_id}"

    def load_history(self, user_id: int) -> list[tuple[str, str]]:
        if not self._redis:
            return []

        try:
            raw_payload = self._redis.get(self._key(user_id))
            if not raw_payload:
                return []

            if isinstance(raw_payload, bytes):
                raw_payload = raw_payload.decode("utf-8")

            decoded = json.loads(raw_payload)
            if not isinstance(decoded, list):
                return []

            history: list[tuple[str, str]] = []
            for item in decoded:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    history.append((str(item[0]), str(item[1])))

            return history
        except Exception:
            logger.exception(
                "Telegram history: failed to load history for user_id=%s", user_id
            )
            return []

    def save_turn(self, user_id, user_message, assistant_message):
        if not self._redis:
            return

        try:
            current = self.load_history(user_id)
            current.append((str(user_message), str(assistant_message)))
            trimmed = current[-self._max_turns :]
            payload = json.dumps([[u, a] for u, a in trimmed], ensure_ascii=False)
            self._redis.setex(self._key(user_id), self._ttl_seconds, payload)
        except Exception:
            logger.exception(
                "Telegram history: failed to save history for user_id=%s", user_id
            )
