"""Small tests of the pure security helpers in manager.py.

Run: python3 -m unittest kiwix/test_manager.py   (from the repository root)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manager  # noqa: E402


class SandboxTests(unittest.TestCase):
    def test_content_is_sandboxed(self):
        for path in (
            "/reader/content/wikipedia_da/A/Hund",
            "/reader/raw/wikipedia_da/content/A/Hund",
            "/reader/content/wikipedia_da/I/billede.png?x=1",
            "/reader//content/x/A/y",
            "/reader/%63ontent/x/A/y",
            "/reader/skin/../content/x/A/y",
            "/reader/viewer/../content/x/A/y",
            "/reader/skin/%2e%2e/content/x/A/y",
            "/reader/unknown",
        ):
            self.assertTrue(manager.needs_sandbox(path, "text/html"), path)

    def test_own_pages_are_not(self):
        for path in (
            "/reader/viewer", "/reader/viewer/", "/reader/viewer?x=1",
            "/reader/search?pattern=hund", "/reader/suggest?term=a",
            "/reader/skin/kiwix.css", "/reader/catalog/v2/entries?count=1",
        ):
            self.assertFalse(manager.needs_sandbox(path, "text/html"), path)

    def test_pdf_is_not(self):
        self.assertFalse(manager.needs_sandbox("/reader/content/x/A/b.pdf", "application/pdf"))
        self.assertFalse(manager.needs_sandbox("/reader/content/x/A/b.pdf", "Application/PDF; x=y"))
        self.assertTrue(manager.needs_sandbox("/reader/content/x/A/b", "application/pdf-not"))

    def test_policy_value(self):
        self.assertEqual(manager.SANDBOX_CSP, "sandbox allow-scripts allow-forms allow-popups")


class PostPolicyTests(unittest.TestCase):
    J = "application/json"

    def test_bookmark_from_sandbox(self):
        self.assertEqual(manager.post_policy("/api/bookmarks", "null", self.J), (0, None, "null"))
        self.assertEqual(manager.post_policy("/api/bookmarks", "null", self.J + "; charset=utf-8")[0], 0)

    def test_other_routes_refuse_null_origin(self):
        for route in ("/api/download", "/api/delete", "/api/visibility", "/api/auto-update"):
            self.assertEqual(manager.post_policy(route, "null", self.J)[0], 403, route)
            self.assertEqual(manager.post_policy(route, "null", "text/plain")[0], 403, route)

    def test_json_required(self):
        for route in ("/api/bookmarks", "/api/download"):
            for ctype in ("", "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
                self.assertEqual(manager.post_policy(route, "", ctype)[0], 415)

    def test_same_origin_unchanged(self):
        self.assertEqual(manager.post_policy("/api/download", "https://ha.example", self.J), (0, None, None))
        self.assertEqual(manager.post_policy("/api/bookmarks", "", self.J), (0, None, None))


if __name__ == "__main__":
    unittest.main()
