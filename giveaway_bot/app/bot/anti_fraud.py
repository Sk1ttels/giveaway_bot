from datetime import datetime, timedelta

def looks_like_fake(user) -> bool:
    # Дуже базово. Потім можна посилити.
    # user.is_bot — якщо true, одразу відсікаємо.
    if getattr(user, "is_bot", False):
        return True

    # Якщо нема ні username, ні імені — підозріло (але не 100%).
    if not user.username and not user.first_name:
        return True

    return False

class SimpleRateLimit:
    def __init__(self):
        self._events = {}

    def allow(self, key: str, limit: int, per_seconds: int) -> bool:
        now = datetime.utcnow()
        arr = self._events.get(key, [])
        arr = [t for t in arr if now - t < timedelta(seconds=per_seconds)]
        if len(arr) >= limit:
            self._events[key] = arr
            return False
        arr.append(now)
        self._events[key] = arr
        return True

rate_limiter = SimpleRateLimit()
