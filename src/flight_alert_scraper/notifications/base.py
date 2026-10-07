from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    def send(self, recipient: str, subject: str, html_body: str, text_body: str) -> None: ...
