import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_network(call: Callable[[], T], attempts: int = 3, base_sleep: float = 1.0) -> T:
    last_error: Exception | None = None
    for idx in range(attempts):
        try:
            return call()
        except Exception as exc:  # requests exceptions are handled by caller use-case
            last_error = exc
            if idx == attempts - 1:
                break
            time.sleep(base_sleep * (2 ** idx))
    assert last_error is not None
    raise last_error

