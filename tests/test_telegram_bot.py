import unittest

try:
    from bot.telegram_bot import TelegramBot
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class TestTruncate(unittest.TestCase):

    def test_short_text(self):
        text = "Hello"
        self.assertEqual(TelegramBot._truncate(text), text)

    def test_exact_limit(self):
        text = "A" * 4096
        self.assertEqual(TelegramBot._truncate(text), text)

    def test_over_limit(self):
        text = "A" * 5000
        result = TelegramBot._truncate(text)
        self.assertLessEqual(len(result), 4096)
        self.assertTrue(result.endswith("… (truncated)"))

    def test_custom_limit(self):
        text = "A" * 200
        result = TelegramBot._truncate(text, limit=100)
        self.assertLessEqual(len(result), 100)


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class TestNotifiedIdsOrdering(unittest.TestCase):

    def test_add_maintains_order(self):
        bot = TelegramBot.__new__(TelegramBot)
        bot._notified_list = []
        bot._notified_set = set()
        bot.MAX_NOTIFIED_IDS = 5

        for i in range(7):
            bot._add_notified(f"id_{i}")

        # should keep last 5
        self.assertEqual(len(bot._notified_list), 5)
        self.assertEqual(bot._notified_list[0], "id_2")
        self.assertEqual(bot._notified_list[-1], "id_6")
        self.assertNotIn("id_0", bot._notified_set)
        self.assertNotIn("id_1", bot._notified_set)

    def test_no_duplicates(self):
        bot = TelegramBot.__new__(TelegramBot)
        bot._notified_list = []
        bot._notified_set = set()
        bot.MAX_NOTIFIED_IDS = 500

        bot._add_notified("id_1")
        bot._add_notified("id_1")
        bot._add_notified("id_1")

        self.assertEqual(len(bot._notified_list), 1)


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class TestUptimeStr(unittest.TestCase):

    def test_minutes(self):
        import time
        bot = TelegramBot.__new__(TelegramBot)
        bot._started_at = time.time() - 300  # 5 min ago
        result = bot._uptime_str()
        self.assertIn("5m", result)

    def test_hours(self):
        import time
        bot = TelegramBot.__new__(TelegramBot)
        bot._started_at = time.time() - 7200  # 2 hours ago
        result = bot._uptime_str()
        self.assertIn("2h", result)


if __name__ == "__main__":
    unittest.main()
