import io
import json
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.logger import logger


class TelegramBot:

    NOTIFIED_IDS_PATH = "data/notified_ids.json"
    MAX_NOTIFIED_IDS = 500

    def __init__(
        self,
        token,
        chat_id,
        gmail_svc=None,
        rule_engine=None,
        rules_path="config/rules.json",
    ):
        self.token = token
        self.allowed_chat_ids = {
            cid.strip() for cid in str(chat_id).split(",") if cid.strip()
        }
        self.gmail_svc = gmail_svc
        self.rule_engine = rule_engine
        self.rules_path = rules_path
        self.app = None
        self._polling_active = True
        self._started_at = time.time()
        self._notified_list, self._notified_set = self._load_notified_ids()
        self._reply_pending = {}

    def _load_notified_ids(self):
        try:
            if os.path.exists(self.NOTIFIED_IDS_PATH):
                with open(self.NOTIFIED_IDS_PATH, "r") as f:
                    ids = json.load(f)
                logger.info("Loaded %d notified email IDs", len(ids))
                return ids, set(ids)
        except Exception as e:
            logger.warning("Failed to load notified_ids: %s", e)
        return [], set()

    def _add_notified(self, msg_id):
        if msg_id not in self._notified_set:
            self._notified_list.append(msg_id)
            self._notified_set.add(msg_id)
        if len(self._notified_list) > self.MAX_NOTIFIED_IDS:
            removed = self._notified_list[: -self.MAX_NOTIFIED_IDS]
            self._notified_list = self._notified_list[-self.MAX_NOTIFIED_IDS :]
            self._notified_set -= set(removed)

    def _save_notified_ids(self):
        try:
            os.makedirs(os.path.dirname(self.NOTIFIED_IDS_PATH), exist_ok=True)
            with open(self.NOTIFIED_IDS_PATH, "w") as f:
                json.dump(self._notified_list, f)
        except Exception as e:
            logger.error("Failed to save notified_ids: %s", e)

    @staticmethod
    def _truncate(text, limit=4096):
        if len(text) <= limit:
            return text
        return text[: limit - 20] + "\n\n… (truncated)"

    async def _is_authorized(self, update):
        user_id = str(update.effective_chat.id)
        if user_id not in self.allowed_chat_ids:
            await update.message.reply_text("⛔ Access denied.")
            logger.warning("Access denied for chat_id: %s", user_id)
            return False
        return True

    def _main_keyboard(self):
        keyboard = [
            [
                InlineKeyboardButton("📊 Status", callback_data="btn_status"),
                InlineKeyboardButton("📬 Inbox", callback_data="btn_inbox"),
            ],
            [
                InlineKeyboardButton("🔍 Check Email", callback_data="btn_check"),
                InlineKeyboardButton("📋 Rules", callback_data="btn_rules"),
            ],
            [
                InlineKeyboardButton("🔄 Reload Rules", callback_data="btn_reload"),
                InlineKeyboardButton("📖 Help", callback_data="btn_help"),
            ],
            [
                InlineKeyboardButton("⏸️ Pause", callback_data="btn_pause"),
                InlineKeyboardButton("▶️ Resume", callback_data="btn_resume"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def cmd_start(self, update, context):
        if not await self._is_authorized(update):
            return
        text = "🤖 *Gmail Bot Active!*\n\nChoose a menu below:"
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=self._main_keyboard()
        )

    async def cmd_help(self, update, context):
        if not await self._is_authorized(update):
            return
        text = (
            "📖 *Gmail Bot Help*\n\n"
            "This bot automatically checks incoming emails "
            "and runs configured rules.\n\n"
            "*Commands:*\n"
            "/status — Polling status & rule count\n"
            "/inbox — View unread emails\n"
            "/check — Check & process emails with rules\n"
            "/trash <number> — Delete email from inbox\n"
            "/reply <number> — Reply to email from Telegram\n"
            "/cancel — Cancel reply\n"
            "/rules — Show active rules\n"
            "/reload — Reload rules.json\n"
            "/pause — Pause auto-polling\n"
            "/resume — Resume auto-polling\n"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    def _uptime_str(self):
        secs = int(time.time() - self._started_at)
        h, m = secs // 3600, (secs % 3600) // 60
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    async def cmd_status(self, update, context):
        if not await self._is_authorized(update):
            return
        num_rules = len(self.rule_engine.rules) if self.rule_engine else 0
        polling_status = "▶️ Active" if self._polling_active else "⏸️ Paused"
        owner = self.gmail_svc.owner_email if self.gmail_svc else "N/A"
        text = (
            f"📊 *Bot Status*\n\n"
            f"*Owner:* {owner}\n"
            f"*Polling:* {polling_status}\n"
            f"*Rules:* {num_rules}\n"
            f"*Uptime:* {self._uptime_str()}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    INBOX_PAGE_SIZE = 10

    def _format_inbox_page(self, details, page, total):
        start = page * self.INBOX_PAGE_SIZE
        page_items = details[start : start + self.INBOX_PAGE_SIZE]
        total_pages = (total + self.INBOX_PAGE_SIZE - 1) // self.INBOX_PAGE_SIZE

        lines = [f"📬 {total} Unread Emails (page {page + 1}/{total_pages}):\n"]
        for i, detail in enumerate(page_items, start + 1):
            sender_name, sender_email = self.gmail_svc.parse_sender(detail["from"])
            if sender_name and sender_name != sender_email:
                display_name = f"{sender_name} <{sender_email}>"
            else:
                display_name = sender_email
            subject = detail["subject"] or "(no subject)"
            if len(subject) > 60:
                subject = subject[:60] + "…"
            snippet = detail.get("snippet", "")[:100]
            gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{detail['id']}"

            att_list = self.gmail_svc.get_attachment_summary(
                detail.get("payload", {})
            )
            att_line = ""
            if att_list:
                att_line = "\n    " + "\n    ".join(att_list) + "\n"

            lines.append(
                f"{i}. 📩 {subject}\n"
                f"    👤 {display_name}\n"
                f"    📝 {snippet}"
                f"{att_line}\n"
                f"    🔗 Open Email ({gmail_link})"
            )
        return "\n\n".join(lines)

    def _inbox_keyboard(self, page, total):
        total_pages = (total + self.INBOX_PAGE_SIZE - 1) // self.INBOX_PAGE_SIZE
        buttons = []
        if page > 0:
            buttons.append(
                InlineKeyboardButton("◀️ Prev", callback_data=f"inbox_page:{page - 1}")
            )
        if page < total_pages - 1:
            buttons.append(
                InlineKeyboardButton("Next ▶️", callback_data=f"inbox_page:{page + 1}")
            )
        rows = []
        if buttons:
            rows.append(buttons)
        rows.append(
            [InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]
        )
        return InlineKeyboardMarkup(rows)

    async def cmd_inbox(self, update, context):
        if not await self._is_authorized(update):
            return
        if not self.gmail_svc:
            await update.message.reply_text("❌ Gmail service not available.")
            return

        await update.message.reply_text("🔍 Fetching emails…")
        try:
            messages = self.gmail_svc.get_unread_messages(max_results=50)
            if not messages:
                await update.message.reply_text("📭 No unread emails.")
                return

            details = self.gmail_svc.fetch_details_batch(messages)

            context.user_data["inbox_cache"] = details
            page = 0
            text = self._format_inbox_page(details, page, len(details))
            kb = self._inbox_keyboard(page, len(details))
            await update.message.reply_text(
                self._truncate(text), disable_web_page_preview=True, reply_markup=kb
            )
        except Exception as e:
            logger.error("Inbox error: %s", e)
            await update.message.reply_text(f"❌ Error: {e}")

    async def cmd_check(self, update, context):
        if not await self._is_authorized(update):
            return
        await update.message.reply_text("🔍 Checking new emails…")

        if not self.gmail_svc or not self.rule_engine:
            await update.message.reply_text("❌ Gmail service not available.")
            return

        try:
            messages = self.gmail_svc.get_unread_messages()
            if not messages:
                await update.message.reply_text("📭 No unread emails.")
                return

            all_logs = []
            matched = 0
            for msg_ref in messages:
                detail = self.gmail_svc.get_message_detail(msg_ref["id"])
                if not detail:
                    continue
                logs = self.rule_engine.process_email(detail)
                if logs:
                    matched += 1
                    header = (
                        f"📧 *{detail['subject']}*\n"
                        f"From: {detail['from']}"
                    )
                    all_logs.append(header)
                    all_logs.extend(logs)
                    all_logs.append("")

            summary = (
                f"📊 Found *{len(messages)}* unread emails\n"
                f"✅ *{matched}* matched rules\n"
            )
            if all_logs:
                report = "\n".join(all_logs)
                await update.message.reply_text(
                    self._truncate(f"{summary}\n{report}"),
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"{summary}\n"
                    "ℹ️ No emails matched any rules.\n"
                    "Use /inbox to view email list.\n"
                    "Edit `config/rules.json` to add rules.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error("Manual check error: %s", e)
            await update.message.reply_text(f"❌ Error: {e}")

    async def cmd_rules(self, update, context):
        if not await self._is_authorized(update):
            return
        if not self.rule_engine or not self.rule_engine.rules:
            await update.message.reply_text("📋 No rules configured.")
            return

        lines = ["📋 Rules:\n"]
        for i, rule in enumerate(self.rule_engine.rules, 1):
            name = rule.get("name", "Unnamed")
            cond = rule.get("condition", {})
            actions = rule.get("actions", {})

            action_list = []
            if actions.get("reply"):
                action_list.append("Reply")
            if actions.get("label"):
                action_list.append(f"Label: {actions['label']}")
            if actions.get("archive"):
                action_list.append("Archive")
            if actions.get("forward_webhook"):
                action_list.append("Webhook")

            lines.append(
                f"{i}. {name}\n"
                f"   Condition: {json.dumps(cond, ensure_ascii=False)}\n"
                f"   Actions: {', '.join(action_list) or 'None'}"
            )

        await update.message.reply_text("\n".join(lines))

    async def cmd_reload(self, update, context):
        if not await self._is_authorized(update):
            return
        if self.rule_engine:
            self.rule_engine.reload_rules(self.rules_path)
            n = len(self.rule_engine.rules)
            await update.message.reply_text(
                f"🔄 Rules reloaded. Total: {n} rules."
            )
        else:
            await update.message.reply_text("❌ Rule engine not available.")

    async def cmd_pause(self, update, context):
        if not await self._is_authorized(update):
            return
        self._polling_active = False
        await update.message.reply_text("⏸️ Auto-polling paused.")

    async def cmd_resume(self, update, context):
        if not await self._is_authorized(update):
            return
        self._polling_active = True
        await update.message.reply_text("▶️ Auto-polling resumed.")

    async def button_callback(self, update, context):
        query = update.callback_query
        await query.answer()

        user_id = str(query.from_user.id)
        if user_id not in self.allowed_chat_ids:
            await query.edit_message_text("⛔ Access denied.")
            return

        data = query.data

        if data.startswith("inbox_page:"):
            page = int(data.split(":")[1])
            await self._cb_inbox_page(query, context, page)
            return

        handlers = {
            "btn_status": self._cb_status,
            "btn_inbox": self._cb_inbox,
            "btn_check": self._cb_check,
            "btn_rules": self._cb_rules,
            "btn_reload": self._cb_reload,
            "btn_help": self._cb_help,
            "btn_pause": self._cb_pause,
            "btn_resume": self._cb_resume,
            "btn_menu": self._cb_menu,
        }

        handler = handlers.get(data)
        if handler:
            await handler(query)

    async def _cb_menu(self, query):
        await query.edit_message_text(
            "🤖 *Gmail Bot Active!*\n\nChoose a menu below:",
            parse_mode="Markdown",
            reply_markup=self._main_keyboard(),
        )

    async def _cb_status(self, query):
        num_rules = len(self.rule_engine.rules) if self.rule_engine else 0
        polling_status = "▶️ Active" if self._polling_active else "⏸️ Paused"
        owner = self.gmail_svc.owner_email if self.gmail_svc else "N/A"
        text = (
            f"📊 *Bot Status*\n\n"
            f"*Owner:* {owner}\n"
            f"*Polling:* {polling_status}\n"
            f"*Rules:* {num_rules}\n"
            f"*Uptime:* {self._uptime_str()}"
        )
        back_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb)

    async def _cb_inbox(self, query):
        if not self.gmail_svc:
            await query.edit_message_text("❌ Gmail service not available.")
            return
        await query.edit_message_text("🔍 Fetching emails…")
        try:
            messages = self.gmail_svc.get_unread_messages(max_results=50)
            if not messages:
                back_kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
                )
                await query.edit_message_text("📭 No unread emails.", reply_markup=back_kb)
                return

            details = self.gmail_svc.fetch_details_batch(messages)

            self._inbox_cache = details
            page = 0
            text = self._format_inbox_page(details, page, len(details))
            kb = self._inbox_keyboard(page, len(details))
            await query.edit_message_text(
                self._truncate(text), disable_web_page_preview=True, reply_markup=kb
            )
        except Exception as e:
            logger.error("Inbox error: %s", e)
            await query.edit_message_text(f"❌ Error: {e}")

    async def _cb_inbox_page(self, query, context, page):
        details = context.user_data.get("inbox_cache") or getattr(
            self, "_inbox_cache", None
        )
        if not details:
            await self._cb_inbox(query)
            return

        text = self._format_inbox_page(details, page, len(details))
        kb = self._inbox_keyboard(page, len(details))
        await query.edit_message_text(
            self._truncate(text), disable_web_page_preview=True, reply_markup=kb
        )

    async def _cb_check(self, query):
        if not self.gmail_svc or not self.rule_engine:
            await query.edit_message_text("❌ Gmail service not available.")
            return
        await query.edit_message_text("🔍 Checking new emails…")
        try:
            messages = self.gmail_svc.get_unread_messages()
            back_kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
            )
            if not messages:
                await query.edit_message_text("📭 No unread emails.", reply_markup=back_kb)
                return

            all_logs = []
            matched = 0
            for msg_ref in messages:
                detail = self.gmail_svc.get_message_detail(msg_ref["id"])
                if not detail:
                    continue
                logs = self.rule_engine.process_email(detail)
                if logs:
                    matched += 1
                    all_logs.append(f"📧 {detail['subject']}\nFrom: {detail['from']}")
                    all_logs.extend(logs)
                    all_logs.append("")

            summary = (
                f"📊 Found {len(messages)} unread emails\n"
                f"✅ {matched} matched rules\n"
            )
            if all_logs:
                report = "\n".join(all_logs)
                await query.edit_message_text(
                    self._truncate(f"{summary}\n{report}"), reply_markup=back_kb
                )
            else:
                await query.edit_message_text(
                    f"{summary}\nℹ️ No emails matched any rules.",
                    reply_markup=back_kb,
                )
        except Exception as e:
            logger.error("Check error: %s", e)
            await query.edit_message_text(f"❌ Error: {e}")

    async def _cb_rules(self, query):
        back_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
        )
        if not self.rule_engine or not self.rule_engine.rules:
            await query.edit_message_text("📋 No rules configured.", reply_markup=back_kb)
            return

        lines = ["📋 Rules:\n"]
        for i, rule in enumerate(self.rule_engine.rules, 1):
            name = rule.get("name", "Unnamed")
            actions = rule.get("actions", {})
            action_list = []
            if actions.get("reply"):
                action_list.append("Reply")
            if actions.get("label"):
                action_list.append(f"Label: {actions['label']}")
            if actions.get("archive"):
                action_list.append("Archive")
            if actions.get("forward_webhook"):
                action_list.append("Webhook")
            lines.append(f"{i}. {name}\n   Actions: {', '.join(action_list) or 'None'}")

        await query.edit_message_text("\n".join(lines), reply_markup=back_kb)

    async def _cb_reload(self, query):
        back_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
        )
        if self.rule_engine:
            self.rule_engine.reload_rules(self.rules_path)
            n = len(self.rule_engine.rules)
            await query.edit_message_text(f"🔄 Rules reloaded. Total: {n} rules.", reply_markup=back_kb)
        else:
            await query.edit_message_text("❌ Rule engine not available.", reply_markup=back_kb)

    async def _cb_help(self, query):
        text = (
            "📖 Gmail Bot Help\n\n"
            "This bot automatically checks incoming emails "
            "and runs configured rules.\n\n"
            "Use the menu buttons or commands:\n"
            "/start — Show main menu\n"
            "/inbox — View unread emails\n"
            "/check — Process emails with rules\n"
            "/trash <no> — Delete email\n"
            "/reply <no> — Reply to email\n"
            "/cancel — Cancel reply\n"
            "/rules — View active rules\n"
            "/reload — Reload rules\n"
            "/pause — Pause polling\n"
            "/resume — Resume polling"
        )
        back_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
        )
        await query.edit_message_text(text, reply_markup=back_kb)

    async def _cb_pause(self, query):
        self._polling_active = False
        back_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
        )
        await query.edit_message_text("⏸️ Auto-polling paused.", reply_markup=back_kb)

    async def _cb_resume(self, query):
        self._polling_active = True
        back_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="btn_menu")]]
        )
        await query.edit_message_text("▶️ Auto-polling resumed.", reply_markup=back_kb)

    async def cmd_trash(self, update, context):
        if not await self._is_authorized(update):
            return
        if not self.gmail_svc:
            await update.message.reply_text("❌ Gmail service not available.")
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: /trash <number>\n"
                "Number from /inbox list."
            )
            return

        try:
            idx = int(args[0]) - 1
        except ValueError:
            await update.message.reply_text("❌ Must be a number.")
            return

        cache = context.user_data.get("inbox_cache") or getattr(self, "_inbox_cache", None)
        if not cache or idx < 0 or idx >= len(cache):
            await update.message.reply_text("❌ Invalid number. Try /inbox first.")
            return

        email = cache[idx]
        ok = self.gmail_svc.trash_message(email["id"])
        if ok:
            await update.message.reply_text(
                f"🗑 Email \"{email['subject']}\" moved to trash."
            )
        else:
            await update.message.reply_text("❌ Failed to delete email.")

    async def cmd_reply(self, update, context):
        if not await self._is_authorized(update):
            return
        if not self.gmail_svc:
            await update.message.reply_text("❌ Gmail service not available.")
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: /reply <number>\n"
                "Number from /inbox list. Bot will ask for reply text."
            )
            return

        try:
            idx = int(args[0]) - 1
        except ValueError:
            await update.message.reply_text("❌ Must be a number.")
            return

        cache = context.user_data.get("inbox_cache") or getattr(self, "_inbox_cache", None)
        if not cache or idx < 0 or idx >= len(cache):
            await update.message.reply_text("❌ Invalid number. Try /inbox first.")
            return

        email = cache[idx]
        cid = str(update.effective_chat.id)
        self._reply_pending[cid] = email
        await update.message.reply_text(
            f"✏️ Reply to: *{email['subject']}*\n"
            f"From: {email['from']}\n\n"
            "Type your reply now (or /cancel to abort):",
            parse_mode="Markdown",
        )

    async def cmd_cancel(self, update, context):
        if not await self._is_authorized(update):
            return
        cid = str(update.effective_chat.id)
        if cid in self._reply_pending:
            del self._reply_pending[cid]
            await update.message.reply_text("❌ Reply cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")

    async def handle_text_message(self, update, context):
        cid = str(update.effective_chat.id)
        if cid not in self.allowed_chat_ids:
            return
        if cid not in self._reply_pending:
            return

        email = self._reply_pending.pop(cid)
        body_text = update.message.text

        result = self.gmail_svc.send_reply(email, body_text)
        if result:
            await update.message.reply_text(
                f"✅ Reply sent to {email['from']}"
            )
        else:
            await update.message.reply_text("❌ Failed to send reply.")

    async def scheduled_check(self, context):
        if not self._polling_active:
            return
        if not self.gmail_svc:
            return

        try:
            messages = self.gmail_svc.get_unread_messages()
            if not messages:
                return

            new_emails = []
            for msg_ref in messages:
                msg_id = msg_ref["id"]
                if msg_id in self._notified_set:
                    continue
                detail = self.gmail_svc.get_message_detail(msg_id)
                if not detail:
                    continue
                new_emails.append(detail)
                self._add_notified(msg_id)

            if not new_emails:
                return

            for email in new_emails:
                sender_name, sender_email = self.gmail_svc.parse_sender(
                    email["from"]
                )
                display_name = sender_name or sender_email
                body = self.gmail_svc.get_body_text(
                    email.get("payload", {}), max_length=2000
                )
                preview = body or email.get("snippet", "")

                attachments = self.gmail_svc.get_attachments(
                    email["id"], email.get("payload", {})
                )
                att_info = ""
                if attachments:
                    att_info = f"\n📎 Attachments: {len(attachments)} file(s)"

                text = self._truncate(
                    f"📨 New Email!\n\n"
                    f"👤 From:\n{display_name}\n\n"
                    f"📋 Subject:\n{email['subject']}\n\n"
                    f"📅 Date:\n{email.get('date', '-')}\n"
                    f"{att_info}\n\n"
                    f"📝 Body:\n{preview}"
                )
                for cid in self.allowed_chat_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=cid,
                            text=text,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to send notification to %s: %s", cid, e
                        )

                for att in attachments:
                    file_obj = io.BytesIO(att["data"])
                    file_obj.name = att["filename"]
                    mime = att["mime_type"]
                    caption = f"📎 {att['filename']}"

                    for cid in self.allowed_chat_ids:
                        try:
                            file_obj.seek(0)
                            if mime.startswith("image/"):
                                await context.bot.send_photo(
                                    chat_id=cid,
                                    photo=file_obj,
                                    caption=caption,
                                )
                            else:
                                await context.bot.send_document(
                                    chat_id=cid,
                                    document=file_obj,
                                    caption=caption,
                                )
                        except Exception as e:
                            logger.error(
                                "Failed to send attachment %s to %s: %s",
                                att["filename"],
                                cid,
                                e,
                            )

            if self.rule_engine:
                for email in new_emails:
                    self.rule_engine.process_email(email)

            self._save_notified_ids()
            logger.info(
                "%d new emails notified", len(new_emails)
            )

        except Exception as e:
            logger.error("Scheduled polling error: %s", e)
            for cid in self.allowed_chat_ids:
                try:
                    await context.bot.send_message(
                        chat_id=cid,
                        text=f"❌ Error polling: {e}",
                    )
                except Exception:
                    pass

    async def send_notification(self, text):
        if self.app and self.app.bot:
            for cid in self.allowed_chat_ids:
                try:
                    await self.app.bot.send_message(
                        chat_id=cid, text=text, parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error("Failed to send Telegram notification to %s: %s", cid, e)

    def build(self, polling_interval=1):
        self.app = Application.builder().token(self.token).build()

        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("inbox", self.cmd_inbox))
        self.app.add_handler(CommandHandler("check", self.cmd_check))
        self.app.add_handler(CommandHandler("rules", self.cmd_rules))
        self.app.add_handler(CommandHandler("reload", self.cmd_reload))
        self.app.add_handler(CommandHandler("pause", self.cmd_pause))
        self.app.add_handler(CommandHandler("resume", self.cmd_resume))
        self.app.add_handler(CommandHandler("trash", self.cmd_trash))
        self.app.add_handler(CommandHandler("reply", self.cmd_reply))
        self.app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.handle_text_message
        ))

        interval_seconds = max(polling_interval * 60, 30)
        if self.app.job_queue is not None:
            self.app.job_queue.run_repeating(
                self.scheduled_check,
                interval=interval_seconds,
                first=5,
                name="email_polling",
            )
            logger.info(
                "Scheduled polling every %d seconds (%.1f min)",
                interval_seconds,
                interval_seconds / 60,
            )

        return self.app

    def run(self, polling_interval=1):
        app = self.build(polling_interval)
        logger.info("Telegram bot started")
        app.run_polling(drop_pending_updates=True)
