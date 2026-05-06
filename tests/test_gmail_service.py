import unittest

from bot.gmail_service import GmailService


class TestParseSender(unittest.TestCase):

    def test_name_and_email(self):
        name, email = GmailService.parse_sender('John Doe <john@example.com>')
        self.assertEqual(name, "John Doe")
        self.assertEqual(email, "john@example.com")

    def test_quoted_name(self):
        name, email = GmailService.parse_sender('"Jane Doe" <jane@test.com>')
        self.assertEqual(name, "Jane Doe")
        self.assertEqual(email, "jane@test.com")

    def test_email_only(self):
        name, email = GmailService.parse_sender("someone@gmail.com")
        self.assertEqual(name, "someone@gmail.com")
        self.assertEqual(email, "someone@gmail.com")

    def test_empty(self):
        name, email = GmailService.parse_sender("")
        self.assertEqual(name, "")
        self.assertEqual(email, "")


class TestGetDomain(unittest.TestCase):

    def test_normal(self):
        self.assertEqual(GmailService.get_domain("user@example.com"), "example.com")

    def test_no_at(self):
        self.assertEqual(GmailService.get_domain("invalid"), "")

    def test_subdomain(self):
        self.assertEqual(GmailService.get_domain("a@mail.example.co.id"), "mail.example.co.id")


class TestHasAttachment(unittest.TestCase):

    def test_with_attachment(self):
        payload = {"parts": [{"filename": "report.pdf", "body": {}}]}
        self.assertTrue(GmailService.has_attachment(payload))

    def test_no_attachment(self):
        payload = {"parts": [{"filename": "", "body": {}}]}
        self.assertFalse(GmailService.has_attachment(payload))

    def test_nested_attachment(self):
        payload = {
            "parts": [
                {
                    "filename": "",
                    "parts": [{"filename": "nested.zip"}],
                }
            ]
        }
        self.assertTrue(GmailService.has_attachment(payload))

    def test_empty_payload(self):
        self.assertFalse(GmailService.has_attachment({}))


class TestGetBodyText(unittest.TestCase):

    def test_truncation(self):
        import base64
        long_text = "A" * 5000
        encoded = base64.urlsafe_b64encode(long_text.encode()).decode()
        payload = {
            "mimeType": "text/plain",
            "body": {"data": encoded},
        }
        result = GmailService.get_body_text(payload, max_length=100)
        self.assertLessEqual(len(result), 101)  # +1 for the … char

    def test_empty_payload(self):
        result = GmailService.get_body_text({})
        self.assertEqual(result, "")


class TestAttachmentSummary(unittest.TestCase):

    def test_icons(self):
        payload = {
            "parts": [
                {"filename": "photo.jpg"},
                {"filename": "doc.pdf"},
                {"filename": "archive.zip"},
                {"filename": "unknown.xyz"},
            ]
        }
        items = GmailService.get_attachment_summary(payload)
        self.assertEqual(len(items), 4)
        self.assertIn("🖼", items[0])
        self.assertIn("📄", items[1])
        self.assertIn("📦", items[2])
        self.assertIn("📎", items[3])


if __name__ == "__main__":
    unittest.main()
