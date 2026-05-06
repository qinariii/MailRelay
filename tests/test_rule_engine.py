import unittest
from unittest.mock import MagicMock

from bot.rule_engine import RuleEngine


def _make_email(from_addr="Test <test@example.com>", subject="Hello", msg_id="abc123"):
    return {
        "id": msg_id,
        "thread_id": "thread1",
        "message_id": "<msg@example.com>",
        "subject": subject,
        "from": from_addr,
        "to": "me@gmail.com",
        "date": "Mon, 1 Jan 2024",
        "snippet": "preview",
        "label_ids": ["INBOX", "UNREAD"],
        "payload": {"parts": []},
    }


class TestMatchCondition(unittest.TestCase):

    def setUp(self):
        self.gmail = MagicMock()
        self.engine = RuleEngine.__new__(RuleEngine)
        self.engine.gmail_svc = self.gmail
        self.engine.rules = []
        self.engine._processed_ids = []

    def test_subject_contains_match(self):
        cond = {"subject_contains": ["invoice"]}
        email = _make_email(subject="Invoice #123")
        self.assertTrue(self.engine._match_condition(cond, email))

    def test_subject_contains_no_match(self):
        cond = {"subject_contains": ["invoice"]}
        email = _make_email(subject="Meeting tomorrow")
        self.assertFalse(self.engine._match_condition(cond, email))

    def test_from_domain_match(self):
        cond = {"from_domain": ["example.com"]}
        email = _make_email(from_addr="Bob <bob@example.com>")
        self.assertTrue(self.engine._match_condition(cond, email))

    def test_from_domain_no_match(self):
        cond = {"from_domain": ["other.com"]}
        email = _make_email(from_addr="Bob <bob@example.com>")
        self.assertFalse(self.engine._match_condition(cond, email))

    def test_from_email_match(self):
        cond = {"from_email": ["bob@example.com"]}
        email = _make_email(from_addr="Bob <bob@example.com>")
        self.assertTrue(self.engine._match_condition(cond, email))

    def test_has_attachment_true(self):
        cond = {"has_attachment": True}
        email = _make_email()
        email["payload"] = {"parts": [{"filename": "file.pdf"}]}
        self.assertTrue(self.engine._match_condition(cond, email))

    def test_has_attachment_false(self):
        cond = {"has_attachment": True}
        email = _make_email()
        email["payload"] = {"parts": [{"filename": ""}]}
        self.assertFalse(self.engine._match_condition(cond, email))

    def test_empty_condition_matches_all(self):
        cond = {}
        email = _make_email()
        self.assertTrue(self.engine._match_condition(cond, email))

    def test_combined_conditions(self):
        cond = {"subject_contains": ["invoice"], "from_domain": ["example.com"]}
        email = _make_email(from_addr="A <a@example.com>", subject="Invoice")
        self.assertTrue(self.engine._match_condition(cond, email))

        email2 = _make_email(from_addr="A <a@other.com>", subject="Invoice")
        self.assertFalse(self.engine._match_condition(cond, email2))


class TestDuplicateGuard(unittest.TestCase):

    def setUp(self):
        self.gmail = MagicMock()
        self.gmail.mark_as_read = MagicMock(return_value=True)
        self.gmail.send_reply = MagicMock(return_value={"id": "sent1"})
        self.gmail.owner_email = "me@gmail.com"

        self.engine = RuleEngine.__new__(RuleEngine)
        self.engine.gmail_svc = self.gmail
        self.engine._processed_ids = []
        self.engine.rules = [
            {
                "name": "test rule",
                "condition": {"subject_contains": ["invoice"]},
                "actions": {"reply": True, "reply_template": "templates/default_reply.txt"},
            }
        ]

    def test_same_email_not_processed_twice(self):
        email = _make_email(subject="Invoice #1", msg_id="msg1")

        # patch template rendering
        self.engine._render_template = MagicMock(return_value="thanks")

        logs1 = self.engine.process_email(email)
        logs2 = self.engine.process_email(email)

        self.assertTrue(len(logs1) > 0)
        self.assertEqual(logs2, [])
        self.gmail.send_reply.assert_called_once()

    def test_different_emails_both_processed(self):
        self.engine._render_template = MagicMock(return_value="thanks")

        email1 = _make_email(subject="Invoice #1", msg_id="msg1")
        email2 = _make_email(subject="Invoice #2", msg_id="msg2")

        logs1 = self.engine.process_email(email1)
        logs2 = self.engine.process_email(email2)

        self.assertTrue(len(logs1) > 0)
        self.assertTrue(len(logs2) > 0)


if __name__ == "__main__":
    unittest.main()
