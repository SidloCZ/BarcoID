"""
Unit tests for RateLimiter and PacingAdvisor.
"""

import time
import unittest
from barcoid.engines.rate_limiter import RateLimiter, PacingAdvisor


class TestRateLimiter(unittest.TestCase):
    """Verifies interval enforcement and pacing advice."""

    def test_rate_limiter_waits_appropriately(self):
        limiter = RateLimiter(min_interval_seconds=0.1)
        start = time.time()
        limiter.wait()
        limiter.wait()
        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 0.08)

    def test_pacing_advisor_warning(self):
        # 10 uncached sequences -> No warning
        warn_small = PacingAdvisor.audit_workload(uncached_count=10, has_local_db=False)
        self.assertIsNone(warn_small)

        # 300 uncached sequences without local DB -> High workload warning
        warn_large = PacingAdvisor.audit_workload(uncached_count=300, has_local_db=False)
        self.assertIsNotNone(warn_large)
        self.assertIn("Workload Warning", warn_large)
        self.assertIn("local BLAST", warn_large)

        # 300 uncached sequences WITH local DB -> No remote warning
        warn_local = PacingAdvisor.audit_workload(uncached_count=300, has_local_db=True)
        self.assertIsNone(warn_local)


if __name__ == "__main__":
    unittest.main()

