"""Tests for a2a-card-lock — deterministic, no network."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import a2a_card_lock as cl


def card(**over):
    c = {
        "name": "demo", "description": "does things", "version": "1.0.0",
        "protocolVersion": "0.2.9", "url": "https://demo.example.com/a2a",
        "skills": [
            {"id": "s1", "name": "One", "description": "first", "tags": ["a"]},
            {"id": "s2", "name": "Two", "description": "second", "tags": ["b"]},
        ],
        "security": [{"oauth": []}],
    }
    c.update(over)
    return c


class TestHashing(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(cl.card_hash(card()), cl.card_hash(card()))

    def test_key_order_irrelevant(self):
        a = {"name": "x", "url": "y"}
        b = {"url": "y", "name": "x"}
        self.assertEqual(cl.card_hash(a), cl.card_hash(b))

    def test_different_cards_different_hash(self):
        self.assertNotEqual(cl.card_hash(card()), cl.card_hash(card(name="other")))

    def test_field_hashes_differ(self):
        fh = cl.field_hashes(card())
        self.assertNotEqual(fh["name"], fh["url"])


class TestPin(unittest.TestCase):
    def test_lock_shape(self):
        lock = cl.pin(card())
        self.assertIn("card_hash", lock)
        self.assertIn("skills", lock)
        self.assertEqual(lock["lock_version"], 1)
        self.assertEqual(lock.get("pinned_at", ""), "")  # empty -> same card -> same lockfile bytes

    def test_skill_map(self):
        lock = cl.pin(card())
        self.assertEqual(set(lock["skills"]), {"s1", "s2"})
        self.assertEqual(lock["skills"]["s1"]["name"], "One")


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.lock = cl.pin(card())

    def test_unchanged(self):
        findings, msg = cl.diff(card(), self.lock)
        self.assertEqual(findings, [])
        self.assertIn("unchanged", msg)

    def test_url_change_breaking(self):
        findings, _ = cl.diff(card(url="https://evil.example.com"), self.lock)
        self.assertTrue(any(s == cl.BREAKING and "url" in m for s, m in findings))

    def test_security_change_breaking(self):
        findings, _ = cl.diff(card(security=[{"oauth": ["admin"]}]), self.lock)
        self.assertTrue(any(s == cl.BREAKING and "security" in m for s, m in findings))

    def test_protocol_change_breaking(self):
        findings, _ = cl.diff(card(protocolVersion="1.0.0"), self.lock)
        self.assertTrue(any("protocolVersion" in m for s, m in findings if s == cl.BREAKING))

    def test_skill_removed_breaking(self):
        c = card()
        c["skills"] = c["skills"][:1]
        findings, _ = cl.diff(c, self.lock)
        self.assertTrue(any("removed" in m for s, m in findings if s == cl.BREAKING))

    def test_skill_added_warning(self):
        c = card()
        c["skills"].append({"id": "s3", "name": "Three", "description": "new", "tags": []})
        findings, _ = cl.diff(c, self.lock)
        self.assertTrue(any("added" in m for s, m in findings if s == cl.WARNING))
        self.assertFalse(any(s == cl.BREAKING for s, m in findings))

    def test_skill_desc_change_breaking(self):
        c = card()
        c["skills"][0]["description"] = "rewritten"
        findings, _ = cl.diff(c, self.lock)
        self.assertTrue(any("description changed" in m for s, m in findings if s == cl.BREAKING))

    def test_tag_change_info_only(self):
        c = card()
        c["skills"][0]["tags"] = ["z"]
        findings, _ = cl.diff(c, self.lock)
        self.assertTrue(any("tags changed" in m for s, m in findings if s == cl.INFO))
        self.assertEqual(cl.classify_severity(findings), 0)


class TestSeverity(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(cl.classify_severity([]), 0)
        self.assertEqual(cl.classify_severity([(cl.INFO, "x")]), 0)
        self.assertEqual(cl.classify_severity([(cl.WARNING, "x")]), 1)
        self.assertEqual(cl.classify_severity([(cl.BREAKING, "x"), (cl.WARNING, "y")]), 2)


class TestLockfileRoundtrip(unittest.TestCase):
    def test_save_load(self):
        lock = cl.pin(card())
        p = "/tmp/cl_test.lock"
        cl.save_lock(lock, p)
        self.assertEqual(cl.load_lock(p), lock)


class SecurityRemovalTest(unittest.TestCase):
    """Dropping auth from a pinned card must be BREAKING, not silent."""

    def test_security_block_removed_is_critical(self):
        pinned = card(security=[{"bearer": []}],
                      securitySchemes={"bearer": {"type": "http", "scheme": "bearer"}})
        lock = cl.pin(pinned)

        stripped = dict(pinned)
        stripped.pop("security", None)
        stripped.pop("securitySchemes", None)

        findings, _summary = cl.diff(stripped, lock)
        messages = " ".join(m for _, m in findings)
        self.assertIn("security removed", messages)
        self.assertTrue(all(sev == cl.BREAKING for sev, _ in findings))


if __name__ == "__main__":
    unittest.main()
