import json
import os

from bot.gmail_service import GmailService
from bot.logger import logger


class RuleEngine:

    MAX_PROCESSED = 1000

    def __init__(self, rules_path, gmail_svc):
        self.gmail_svc = gmail_svc
        self.rules = self._load_rules(rules_path)
        self._processed_ids = []

    @staticmethod
    def _load_rules(path):
        if not os.path.exists(path):
            logger.warning("Rules file not found: %s", path)
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("rules", [])
        logger.info("Loaded %d rules from %s", len(rules), path)
        return rules

    def reload_rules(self, path):
        self.rules = self._load_rules(path)

    def _match_condition(self, condition, email_data):
        sender_name, sender_email = GmailService.parse_sender(
            email_data.get("from", "")
        )
        sender_domain = GmailService.get_domain(sender_email)
        subject = email_data.get("subject", "").lower()

        subj_keywords = condition.get("subject_contains", [])
        if subj_keywords:
            if not any(kw.lower() in subject for kw in subj_keywords):
                return False

        from_domains = condition.get("from_domain", [])
        if from_domains:
            if not any(
                sender_domain == d.lower() for d in from_domains
            ):
                return False

        from_emails = condition.get("from_email", [])
        if from_emails:
            if not any(
                sender_email.lower() == e.lower() for e in from_emails
            ):
                return False

        if "has_attachment" in condition:
            has_att = GmailService.has_attachment(
                email_data.get("payload", {})
            )
            if condition["has_attachment"] != has_att:
                return False

        return True

    def _render_template(self, template_path, email_data):
        if not os.path.exists(template_path):
            logger.warning("Template not found: %s", template_path)
            return ""

        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        sender_name, sender_email = GmailService.parse_sender(
            email_data.get("from", "")
        )

        variables = {
            "sender_name": sender_name or sender_email,
            "sender_email": sender_email,
            "subject": email_data.get("subject", ""),
            "date": email_data.get("date", ""),
            "owner_email": self.gmail_svc.owner_email,
        }

        for key, value in variables.items():
            template = template.replace(f"{{{key}}}", value)

        return template

    def _execute_actions(self, actions, email_data, rule_name):
        logs = []
        msg_id = email_data["id"]

        if actions.get("reply"):
            template_path = actions.get(
                "reply_template", "templates/default_reply.txt"
            )
            body = self._render_template(template_path, email_data)
            if body:
                result = self.gmail_svc.send_reply(email_data, body)
                if result:
                    logs.append(f"✉️ Reply sent (rule: {rule_name})")
                else:
                    logs.append(f"❌ Reply failed (rule: {rule_name})")
            else:
                logs.append(f"⚠️ Empty template, reply skipped (rule: {rule_name})")

        label_name = actions.get("label")
        if label_name:
            ok = self.gmail_svc.apply_label(msg_id, label_name)
            if ok:
                logs.append(f"🏷️ Label '{label_name}' applied (rule: {rule_name})")
            else:
                logs.append(f"❌ Label failed (rule: {rule_name})")

        webhook_url = actions.get("forward_webhook")
        if webhook_url:
            ok = GmailService.forward_to_webhook(webhook_url, email_data)
            if ok:
                logs.append(f"🔗 Webhook forwarded (rule: {rule_name})")
            else:
                logs.append(f"❌ Webhook forward failed (rule: {rule_name})")

        if actions.get("archive"):
            ok = self.gmail_svc.archive_message(msg_id)
            if ok:
                logs.append(f"📦 Email archived (rule: {rule_name})")
            else:
                logs.append(f"❌ Archive failed (rule: {rule_name})")

        return logs

    def process_email(self, email_data):
        msg_id = email_data["id"]
        if msg_id in self._processed_ids:
            return []

        all_logs = []
        subject = email_data.get("subject", "(no subject)")
        sender = email_data.get("from", "unknown")

        for rule in self.rules:
            condition = rule.get("condition", {})
            actions = rule.get("actions", {})
            rule_name = rule.get("name", "Unnamed")

            if self._match_condition(condition, email_data):
                logger.info(
                    "Rule '%s' matched email from %s: %s",
                    rule_name,
                    sender,
                    subject,
                )
                logs = self._execute_actions(actions, email_data, rule_name)
                all_logs.extend(logs)

        if all_logs:
            self._processed_ids.append(msg_id)
            if len(self._processed_ids) > self.MAX_PROCESSED:
                self._processed_ids = self._processed_ids[-self.MAX_PROCESSED:]
            self.gmail_svc.mark_as_read(msg_id)

        return all_logs
