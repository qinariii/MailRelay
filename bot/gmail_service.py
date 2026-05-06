import base64
import re
import time
from email.mime.text import MIMEText

import requests

from bot.logger import logger


class GmailService:

    def __init__(self, service, owner_email):
        self.service = service
        self.owner_email = owner_email
        self._label_cache = {}

    def get_unread_messages(self, max_results=20):
        try:
            results = (
                self.service.users()
                .messages()
                .list(
                    userId="me",
                    labelIds=["INBOX", "UNREAD"],
                    maxResults=max_results,
                )
                .execute()
            )
            messages = results.get("messages", [])
            logger.info("Found %d unread emails", len(messages))
            return messages
        except Exception as e:
            logger.error("Failed to fetch emails: %s", e)
            return []

    def get_message_detail(self, msg_id):
        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            return {
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "message_id": headers.get("message-id", ""),
                "subject": headers.get("subject", "(no subject)"),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "snippet": msg.get("snippet", ""),
                "label_ids": msg.get("labelIds", []),
                "payload": msg.get("payload", {}),
            }
        except Exception as e:
            logger.error("Failed to fetch email detail %s: %s", msg_id, e)
            return None

    def fetch_details_batch(self, messages, delay=0.1):
        details = []
        for i, msg_ref in enumerate(messages):
            detail = self.get_message_detail(msg_ref["id"])
            if detail:
                details.append(detail)
            if delay and i < len(messages) - 1:
                time.sleep(delay)
        return details

    @staticmethod
    def parse_sender(from_header):
        match = re.match(r"^(.*?)\s*<(.+?)>$", from_header)
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
        else:
            name = from_header.strip()
            email = from_header.strip()
        return name, email

    @staticmethod
    def get_domain(email_address):
        if "@" in email_address:
            return email_address.split("@")[1].lower()
        return ""

    @staticmethod
    def get_body_text(payload, max_length=2000):
        def _extract_text(part):
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if mime == "text/plain" and data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            for sub in part.get("parts", []):
                result = _extract_text(sub)
                if result:
                    return result
            return ""

        text = _extract_text(payload).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        if len(text) > max_length:
            text = text[:max_length] + "…"
        return text

    @staticmethod
    def has_attachment(payload):
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("filename"):
                return True
            if part.get("parts"):
                for sub in part["parts"]:
                    if sub.get("filename"):
                        return True
        return False

    @staticmethod
    def get_attachment_summary(payload):
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic"}
        video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

        items = []

        def _collect(parts):
            for part in parts:
                filename = part.get("filename", "")
                if filename:
                    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                    dot_ext = f".{ext}"
                    if dot_ext in image_exts:
                        icon = "🖼"
                    elif dot_ext in video_exts:
                        icon = "🎥"
                    elif ext == "pdf":
                        icon = "📄"
                    elif ext in ("doc", "docx"):
                        icon = "📝"
                    elif ext in ("xls", "xlsx"):
                        icon = "📊"
                    elif ext in ("zip", "rar", "7z"):
                        icon = "📦"
                    else:
                        icon = "📎"
                    items.append(f"{icon} {filename}")
                if part.get("parts"):
                    _collect(part["parts"])

        _collect(payload.get("parts", []))
        return items

    def get_attachments(self, msg_id, payload):
        attachments = []

        def _collect(parts):
            for part in parts:
                filename = part.get("filename", "")
                mime_type = part.get("mimeType", "application/octet-stream")
                body = part.get("body", {})
                att_id = body.get("attachmentId")

                if filename and att_id:
                    try:
                        att = (
                            self.service.users()
                            .messages()
                            .attachments()
                            .get(userId="me", messageId=msg_id, id=att_id)
                            .execute()
                        )
                        raw_data = base64.urlsafe_b64decode(
                            att.get("data", "")
                        )
                        attachments.append({
                            "filename": filename,
                            "mime_type": mime_type,
                            "data": raw_data,
                            "size": len(raw_data),
                        })
                        logger.info(
                            "Downloaded attachment: %s (%d bytes)",
                            filename,
                            len(raw_data),
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to download attachment %s: %s", filename, e
                        )

                if part.get("parts"):
                    _collect(part["parts"])

        _collect(payload.get("parts", []))
        return attachments

    def send_reply(self, original_msg, body_text):
        try:
            sender_name, sender_email = self.parse_sender(original_msg["from"])
            subject = original_msg["subject"]
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            message = MIMEText(body_text)
            message["to"] = sender_email
            message["from"] = self.owner_email
            message["subject"] = subject
            orig_msg_id = original_msg.get("message_id", "")
            if orig_msg_id:
                message["In-Reply-To"] = orig_msg_id
                message["References"] = orig_msg_id

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            sent = (
                self.service.users()
                .messages()
                .send(
                    userId="me",
                    body={
                        "raw": raw,
                        "threadId": original_msg["thread_id"],
                    },
                )
                .execute()
            )
            logger.info(
                "Reply sent to %s (subject: %s)", sender_email, subject
            )
            return sent
        except Exception as e:
            logger.error("Failed to send reply: %s", e)
            return None

    def _get_or_create_label(self, label_name):
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        try:
            results = (
                self.service.users().labels().list(userId="me").execute()
            )
            for label in results.get("labels", []):
                if label["name"].lower() == label_name.lower():
                    self._label_cache[label_name] = label["id"]
                    return label["id"]

            new_label = (
                self.service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": label_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            label_id = new_label["id"]
            self._label_cache[label_name] = label_id
            logger.info("Label '%s' created (ID: %s)", label_name, label_id)
            return label_id
        except Exception as e:
            logger.error("Failed to get/create label '%s': %s", label_name, e)
            return None

    def apply_label(self, msg_id, label_name):
        label_id = self._get_or_create_label(label_name)
        if not label_id:
            return False
        try:
            self.service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            logger.info("Label '%s' applied to email %s", label_name, msg_id)
            return True
        except Exception as e:
            logger.error("Failed to apply label: %s", e)
            return False

    def archive_message(self, msg_id):
        try:
            self.service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
            logger.info("Email %s archived", msg_id)
            return True
        except Exception as e:
            logger.error("Failed to archive email %s: %s", msg_id, e)
            return False

    def trash_message(self, msg_id):
        try:
            self.service.users().messages().trash(
                userId="me", id=msg_id
            ).execute()
            logger.info("Email %s moved to trash", msg_id)
            return True
        except Exception as e:
            logger.error("Failed to trash email %s: %s", msg_id, e)
            return False

    def mark_as_read(self, msg_id):
        try:
            self.service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            logger.debug("Email %s marked as read", msg_id)
            return True
        except Exception as e:
            logger.error("Failed to mark email %s: %s", msg_id, e)
            return False

    @staticmethod
    def forward_to_webhook(webhook_url, email_data):
        payload = {
            "text": (
                f"📧 *New Email*\n"
                f"*From:* {email_data.get('from', 'N/A')}\n"
                f"*Subject:* {email_data.get('subject', 'N/A')}\n"
                f"*Date:* {email_data.get('date', 'N/A')}\n"
                f"*Preview:* {email_data.get('snippet', '')[:200]}"
            )
        }
        try:
            resp = requests.post(
                webhook_url, json=payload, timeout=10
            )
            if resp.status_code in (200, 204):
                logger.info("Email forwarded to webhook")
                return True
            else:
                logger.warning(
                    "Webhook response: %d %s", resp.status_code, resp.text
                )
                return False
        except Exception as e:
            logger.error("Failed to forward to webhook: %s", e)
            return False
