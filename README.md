# 📬 Gmail Bot

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-latest-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Gmail API](https://img.shields.io/badge/Gmail%20API-v1-EA4335?logo=gmail&logoColor=white)](https://developers.google.com/gmail/api)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A Telegram-controlled bot that automates Gmail workflows — auto-reply, labeling, archiving, and webhook forwarding — all driven by a simple JSON rule engine.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Rules](#rules)
- [Reply Templates](#reply-templates)
- [Telegram Commands](#telegram-commands)
- [Docker](#docker)
- [Testing](#testing)
- [Security](#security)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| **Auto-reply** | Send template-based replies to matching emails |
| **Labeling** | Automatically label emails based on rules |
| **Archiving** | Archive emails after processing |
| **Webhook forwarding** | Forward email data to Slack, Discord, or any webhook |
| **Scheduled polling** | Periodically check for new unread emails |
| **Telegram control** | Full bot control via Telegram — inbox, check, reply, trash, pause/resume |
| **Duplicate guard** | Prevents processing the same email twice |
| **Attachment support** | Downloads and forwards attachments via Telegram |
| **Log rotation** | Rotating log files with configurable size limits |
| **Graceful shutdown** | Saves state on SIGINT/SIGTERM |

---

## Project Structure

```
gmail-bot/
├── main.py                  # Entry point
├── bot/
│   ├── auth.py              # OAuth 2.0 authentication
│   ├── gmail_service.py     # Gmail API wrapper
│   ├── rule_engine.py       # JSON rule matching & execution
│   ├── telegram_bot.py      # Telegram bot handlers
│   └── logger.py            # Logging configuration
├── config/
│   └── rules.json           # Rule definitions
├── templates/
│   ├── default_reply.txt    # Default auto-reply
│   ├── invoice_reply.txt    # Invoice-specific reply
│   └── ooo_reply.txt        # Out-of-office reply
├── tests/                   # Unit tests
├── Dockerfile
├── .env.example
├── requirements.txt
└── README.md
```

---

## Prerequisites

- **Python 3.10+**
- **Google Cloud project** with Gmail API enabled
- **Telegram bot token** from [@BotFather](https://t.me/BotFather)

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/gmail-bot.git
cd gmail-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Google Cloud

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Navigate to **APIs & Services → Library** and enable **Gmail API**
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID** (Desktop App)
5. Download the JSON file and save it as `credentials.json` in the project root

### 4. Create a Telegram bot

1. Open [@BotFather](https://t.me/BotFather) on Telegram and create a new bot
2. Copy the bot token
3. Get your chat ID from [@userinfobot](https://t.me/userinfobot)

### 5. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
POLLING_INTERVAL=5
OWNER_EMAIL=you@gmail.com
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789
```

### 6. Authenticate & run

```bash
# First-time OAuth login
python main.py --auth

# Start the bot
python main.py
```

---

## Configuration

| Variable | Description | Default |
|---|---|---|
| `POLLING_INTERVAL` | Email check interval in minutes | `5` |
| `OWNER_EMAIL` | Your Gmail address | — |
| `TOKEN_PATH` | Path to OAuth token file | `token.json` |
| `CREDENTIALS_PATH` | Path to OAuth credentials file | `credentials.json` |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | — |
| `TELEGRAM_CHAT_ID` | Allowed chat IDs (comma-separated) | — |
| `RULES_PATH` | Path to rules JSON file | `config/rules.json` |

---

## Rules

Rules are defined in `config/rules.json`. Each rule has a **condition** (when to trigger) and **actions** (what to do).

### Conditions

| Key | Type | Description |
|---|---|---|
| `subject_contains` | `string[]` | Match if subject contains any keyword (case-insensitive) |
| `from_domain` | `string[]` | Match sender's email domain |
| `from_email` | `string[]` | Match sender's exact email address |
| `has_attachment` | `bool` | Match if email has attachments |

### Actions

| Key | Type | Description |
|---|---|---|
| `reply` | `bool` | Send an auto-reply |
| `reply_template` | `string` | Path to reply template file |
| `label` | `string` | Apply a Gmail label (created if not exists) |
| `archive` | `bool` | Remove from inbox |
| `forward_webhook` | `string` | POST email data to a webhook URL |

### Example

```json
{
  "rules": [
    {
      "name": "Auto-reply invoice emails",
      "condition": {
        "subject_contains": ["invoice", "billing", "payment"]
      },
      "actions": {
        "reply": true,
        "reply_template": "templates/invoice_reply.txt",
        "label": "Invoice"
      }
    }
  ]
}
```

---

## Reply Templates

Templates in `templates/` support the following variables:

| Variable | Value |
|---|---|
| `{sender_name}` | Sender's display name |
| `{sender_email}` | Sender's email address |
| `{subject}` | Email subject line |
| `{date}` | Email date |
| `{owner_email}` | Your email address |

**Example** (`templates/default_reply.txt`):

```
Hi {sender_name},

Thank you for reaching out.

We have received your email regarding "{subject}" and will get back to you shortly.

Regards,
{owner_email}
```

---

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Show main menu with inline buttons |
| `/status` | Bot status, uptime, and rule count |
| `/inbox` | Browse unread emails (paginated) |
| `/check` | Force-check and process emails with rules |
| `/trash <n>` | Move email #n to trash (from `/inbox` list) |
| `/reply <n>` | Reply to email #n directly from Telegram |
| `/cancel` | Cancel a pending reply |
| `/rules` | Display all active rules |
| `/reload` | Hot-reload `rules.json` without restart |
| `/pause` | Pause scheduled polling |
| `/resume` | Resume scheduled polling |
| `/help` | Show help message |

---

## Docker

Build and run with Docker:

```bash

docker build -t gmail-bot .
touch token.json
docker run -it \
  --name gmail-bot \
  --env-file .env \
  -v $(pwd)/token.json:/app/token.json \
  -v $(pwd)/credentials.json:/app/credentials.json \
  gmail-bot
```

> **Note:** Run `python main.py --auth` locally first to generate `token.json` before deploying with Docker.

---

## Testing

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

Tests cover:
- Email parsing (`parse_sender`, `get_domain`, `has_attachment`)
- Body text extraction and truncation
- Attachment summary with file type icons
- Rule condition matching (subject, domain, email, attachment)
- Duplicate reply guard
- Telegram message truncation
- Notified ID ordering and deduplication
- Uptime string formatting

---

## Security

- **OAuth tokens** are stored locally and excluded via `.gitignore` — never commit `token.json` or `credentials.json`
- **Token auto-refresh** — expired tokens are refreshed automatically; revoked tokens trigger re-authentication
- **Telegram access control** — only whitelisted chat IDs can interact with the bot
- **No hardcoded secrets** — all sensitive values are loaded from environment variables

---

## License

This project is licensed under the [MIT License](LICENSE).
