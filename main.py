import argparse
import os
import signal
import sys

from dotenv import load_dotenv

from bot.auth import authenticate, get_gmail_service
from bot.gmail_service import GmailService
from bot.logger import logger
from bot.rule_engine import RuleEngine
from bot.telegram_bot import TelegramBot


def parse_args():
    parser = argparse.ArgumentParser(description="Gmail auto-reply & rule bot")
    parser.add_argument(
        "--auth",
        action="store_true",
        help="Only run OAuth 2.0 authentication (first-time login)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once without polling (no Telegram bot)",
    )
    return parser.parse_args()


def main():
    load_dotenv()

    credentials_path = os.getenv("CREDENTIALS_PATH", "credentials.json")
    token_path = os.getenv("TOKEN_PATH", "token.json")
    owner_email = os.getenv("OWNER_EMAIL", "")
    polling_interval = float(os.getenv("POLLING_INTERVAL", "1"))
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    rules_path = os.getenv("RULES_PATH", "config/rules.json")

    args = parse_args()

    if args.auth:
        logger.info("Mode: Auth only")
        authenticate(credentials_path, token_path)
        logger.info("Auth successful! Token saved to %s", token_path)
        return

    if not owner_email:
        logger.error("OWNER_EMAIL not set in .env")
        sys.exit(1)

    service = get_gmail_service(credentials_path, token_path)
    gmail_svc = GmailService(service, owner_email)
    rule_engine = RuleEngine(rules_path, gmail_svc)

    logger.info("Gmail Bot started for %s", owner_email)
    logger.info("Rules loaded: %d", len(rule_engine.rules))

    if args.once:
        logger.info("Mode: Single run")
        messages = gmail_svc.get_unread_messages()
        if not messages:
            logger.info("No new emails.")
            return

        for msg_ref in messages:
            detail = gmail_svc.get_message_detail(msg_ref["id"])
            if not detail:
                continue
            logs = rule_engine.process_email(detail)
            for log_line in logs:
                logger.info(log_line)

        logger.info("Processed %d emails.", len(messages))
        return

    if not telegram_token:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not telegram_chat_id:
        logger.error("TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    telegram_bot = TelegramBot(
        token=telegram_token,
        chat_id=telegram_chat_id,
        gmail_svc=gmail_svc,
        rule_engine=rule_engine,
        rules_path=rules_path,
    )

    def shutdown_handler(sig, frame):
        logger.info("Shutdown signal received, saving state…")
        telegram_bot._save_notified_ids()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    telegram_bot.run(polling_interval=polling_interval)


if __name__ == "__main__":
    main()
