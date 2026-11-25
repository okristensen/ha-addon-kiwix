"""Tests of the pure logic in bridge.py (no network).

Run from the repository root: python3 -m unittest supabase_bridge/test_bridge.py
aiohttp is replaced by an empty stub when it is not installed.
"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import aiohttp  # noqa: F401
except ImportError:
    stub = types.ModuleType("aiohttp")
    stub.ClientTimeout = lambda **kw: None
    sys.modules["aiohttp"] = stub
import bridge  # noqa: E402


class FakeHA:
    def __init__(self):
        self.calls = []

    async def rest_service(self, path, data):
        self.calls.append((path, data))


def make_bridge():
    b = bridge.Bridge.__new__(bridge.Bridge)
    b.ha = FakeHA()
    b.alarms = bridge.AlarmThrottle()
    b.options = {"commands": {("stoevsuger", "start"): {}}}
    return b


class ThrottleTests(unittest.TestCase):
    def test_holds_for_30_minutes_per_kind(self):
        now = [1000.0]
        t = bridge.AlarmThrottle(clock=lambda: now[0])
        self.assertTrue(t.allow("a"))
        self.assertFalse(t.allow("a"))
        self.assertTrue(t.allow("b"))  # another kind is independent
        now[0] += 29 * 60
        self.assertFalse(t.allow("a"))
        now[0] += 61
        self.assertTrue(t.allow("a"))


class CanaryTests(unittest.TestCase):
    commands = {("stoevsuger", "start"): {}}

    def test_unlisted(self):
        self.assertFalse(bridge.is_unlisted_command(self.commands, {"app": "stoevsuger", "kommando": "start"}))
        self.assertTrue(bridge.is_unlisted_command(self.commands, {"app": "stoevsuger", "kommando": "vagt_kanarie"}))
        self.assertTrue(bridge.is_unlisted_command(self.commands, {"app": "x", "kommando": "start"}))
        self.assertTrue(bridge.is_unlisted_command({("a", "vagt_kanarie"): {}}, {"app": "a", "kommando": "vagt_kanarie"}))

    def test_clean_text(self):
        self.assertEqual(bridge.clean_text("abcdef123456", 8), "abcdef12")
        self.assertNotIn("[", bridge.clean_text("[x](http://e)"))

    def test_alarm_sends_two_calls_then_throttles(self):
        b = make_bridge()
        asyncio.run(b.alarm("kanarie", "T", "M", "id"))
        asyncio.run(b.alarm("kanarie", "T", "M", "id"))
        self.assertEqual([c[0] for c in b.ha.calls],
                         ["persistent_notification/create", "notify/mobile_app_oles_iphone"])

    def test_canary_never_runs(self):
        b = make_bridge()
        b.options["commands"][("stoevsuger", "vagt_kanarie")] = {"service": "a.b", "entity_id": "a.b", "data": {}, "args": {}}
        from datetime import datetime, timezone, timedelta
        row = {"app": "stoevsuger", "kommando": "vagt_kanarie", "argumenter": {},
               "udloeber": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()}
        b.recent_commands = []
        self.assertEqual(asyncio.run(b.decide(row))[0], "afvist")


if __name__ == "__main__":
    unittest.main()
