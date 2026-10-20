"""Sending email through Resend (https://resend.com) over its HTTP API.

A Django email backend, so everything that already sends mail — password
reset, account notices — goes through it unchanged. Selected automatically
when RESEND_API_KEY is set (config/settings.py). The sender is each message's
`from_email`, which defaults to DEFAULT_FROM_EMAIL; its domain must be verified
in Resend.
"""

import base64
import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, api_key=None, timeout=None, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or settings.RESEND_API_KEY
        self.timeout = timeout or settings.EMAIL_TIMEOUT
        self.session = None

    def open(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update(
                {"Authorization": f"Bearer {self.api_key}", "User-Agent": "easy-apply"}
            )
            return True
        return False

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        if not self.api_key:
            if self.fail_silently:
                return 0
            raise RuntimeError("RESEND_API_KEY is not set.")
        created = self.open()
        sent = 0
        try:
            for message in email_messages:
                if self._send(message):
                    sent += 1
        finally:
            if created:
                self.close()
        return sent

    def _payload(self, message) -> dict:
        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)
        if message.extra_headers:
            payload["headers"] = {str(k): str(v) for k, v in message.extra_headers.items()}
        body_key = "html" if message.content_subtype == "html" else "text"
        payload[body_key] = message.body
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                payload["html"] = content
        attachments = []
        for attachment in message.attachments:
            if isinstance(attachment, tuple):
                filename, content, _mimetype = attachment
            else:  # a MIMEBase part
                filename = attachment.get_filename()
                content = attachment.get_payload(decode=True)
            if isinstance(content, str):
                content = content.encode()
            attachments.append({"filename": filename, "content": base64.b64encode(content).decode("ascii")})
        if attachments:
            payload["attachments"] = attachments
        return payload

    def _send(self, message) -> bool:
        if not message.recipients():
            return False
        try:
            response = self.session.post(settings.RESEND_API_URL, json=self._payload(message), timeout=self.timeout)
        except requests.RequestException:
            logger.exception("Resend could not be reached")
            if not self.fail_silently:
                raise
            return False
        if response.status_code >= 300:
            # Resend explains the refusal (unverified domain, bad key...) in the body.
            logger.error("Resend refused an email: %s %s", response.status_code, response.text[:500])
            if not self.fail_silently:
                raise RuntimeError(f"Resend refused the email (HTTP {response.status_code}).")
            return False
        return True
