"""
Rate limiting, adaptive pacing, and backoff utilities for BarcoID external APIs.
"""

import time
import logging
from typing import Callable, Any, Optional

logger = logging.getLogger("barcoid.engines.rate_limiter")


class RateLimiter:
    """Enforces minimum intervals between external HTTP requests."""

    def __init__(self, min_interval_seconds: float = 1.0):
        self.min_interval = max(0.0, min_interval_seconds)
        self.last_call_time: float = 0.0

    def wait(self):
        """Sleeps if necessary to satisfy the minimum interval since the last call."""
        if self.min_interval <= 0:
            return
        now = time.time()
        elapsed = now - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()


def execute_with_backoff(
    action: Callable[[], Any],
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    action_name: str = "API request",
) -> Any:
    """
    Executes a callable with exponential backoff on transient errors (429, 503, timeouts).
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            return action()
        except Exception as exc:
            last_exception = exc
            is_rate_limit = "429" in str(exc) or "Too Many Requests" in str(exc)
            if attempt < max_retries:
                wait_time = delay * (1.5 if is_rate_limit else 1.0)
                logger.warning(
                    f"[{action_name}] Attempt {attempt}/{max_retries} failed: {exc}. "
                    f"Backing off for {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
                delay *= backoff_factor
            else:
                logger.error(f"[{action_name}] All {max_retries} attempts failed: {exc}")
                raise last_exception


class PacingAdvisor:
    """Evaluates query workload and advises on safety limits and local BLAST necessity."""

    @staticmethod
    def audit_workload(
        uncached_count: int,
        has_local_db: bool = False,
        max_remote_blast_threshold: int = 150,
    ) -> Optional[str]:
        """
        Returns a warning string if workload poses a risk of remote rate-limiting or excessive runtime.
        """
        if uncached_count == 0:
            return None

        if uncached_count > max_remote_blast_threshold and not has_local_db:
            return (
                f"Workload Warning: You have {uncached_count} uncached sequences queued for remote NCBI QBLAST. "
                f"Querying more than {max_remote_blast_threshold} sequences remotely may take >30-60 minutes "
                f"and risks NCBI queue stalls or rate-limiting. "
                f"Recommendation: Use local BLAST with --local-blast-db <path> or limit pilot testing with --max-sequences <N>."
            )
        return None
