"""Test Context class from gitzconsul"""

import logging
import signal
import unittest

from gitzconsul import Context


class TestContext(unittest.TestCase):
    """Test Context class"""

    def _make_context(self, **overrides):
        options = {"logfile": None, "loglevel": "DEBUG"}
        options.update(overrides)
        return Context(options)

    def test_init_defaults(self):
        ctx = self._make_context()
        self.assertFalse(ctx.kill_now)
        self.assertIsInstance(ctx.on_exit, dict)

    def test_instances_do_not_share_state(self):
        ctx1 = self._make_context()
        ctx2 = self._make_context()
        ctx1.on_exit["cb"] = lambda: None
        self.assertNotIn("cb", ctx2.on_exit)

    def test_configure_logging_with_loglevel(self):
        self._make_context(loglevel="WARNING")
        from gitzconsul import log

        self.assertEqual(log.level, logging.WARNING)

    def test_configure_logging_invalid_loglevel(self):
        # Should not raise, just log an error
        self._make_context(loglevel="INVALID")

    def test_configure_logging_with_logfile(self, tmp_path=None):
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            logfile = f.name
        try:
            self._make_context(logfile=logfile)
        finally:
            os.unlink(logfile)

    def test_register_on_exit(self):
        ctx = self._make_context()
        called = []
        ctx.register_on_exit("test", lambda: called.append(True))
        self.assertIn("test", ctx.on_exit)

    def test_exit_gracefully(self):
        ctx = self._make_context()
        called = []
        ctx.register_on_exit("cb", lambda: called.append(True))
        ctx._exit_gracefully(signal.SIGTERM, None)
        self.assertTrue(ctx.kill_now)
        self.assertEqual(called, [True])

    def test_ignore_signal(self):
        ctx = self._make_context()
        # Should not raise
        ctx._ignore_signal(signal.SIGUSR1, None)

    def test_log_signal_caches_names(self):
        ctx = self._make_context()
        self.assertIsNone(ctx._sig2name)
        ctx._log_signal(signal.SIGTERM)
        self.assertIsNotNone(ctx._sig2name)
        # Second call uses cache
        ctx._log_signal(signal.SIGTERM)
