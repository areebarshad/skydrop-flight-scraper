"""Gmail SMTP notifier with STARTTLS."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

_HOST = "smtp.gmail.com"
_PORT = 587


class SmtpNotifier:
    def __init__(self, user: str, app_password: str) -> None:
        self._user = user
        self._password = app_password

    def send(self, recipient: str, subject: str, html_body: str, text_body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._user
        msg["To"] = recipient
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        log.info("Sending email to %s: %s", recipient, subject)
        with smtplib.SMTP(_HOST, _PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(self._user, self._password)
            server.sendmail(self._user, recipient, msg.as_string())
        log.info("Email delivered to %s", recipient)
