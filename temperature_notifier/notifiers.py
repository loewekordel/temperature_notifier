"""
This module defines the Notifier class and its subclasses
for sending notifications.
"""

import logging
from abc import ABC

from simplepush import send as send_simplepush

logger = logging.getLogger(__name__)


class NotifierError(Exception):
    """Custom exception for Notifier errors."""


class Notifier(ABC):
    """Abstract base class for sending notifications."""

    def send_notification(self, title: str, message: str) -> None:
        """
        Sends a notification with the given title and message.

        :param title: The title of the notification.
        :param message: The message of the notification.
        :raises: NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class SimplePushNotifier:
    """Notifier class for sending notifications using Simplepush."""

    def __init__(self, key: str) -> None:
        """
        Initializes the SimplePushNotifier with the provided Simplepush key.

        :param key: The Simplepush key for sending notifications.
        """
        self.key = key

    def send_notification(self, title: str, message: str) -> None:
        """
        Sends a notification using Simplepush.

        :param title: The title of the notification.
        :param message: The message of the notification.
        :raises NotifierError: If sending the notification fails.
        """
        try:
            send_simplepush(self.key, message, title)
            logger.info("Notification sent successfully.")
        except ValueError as e:
            raise NotifierError(f"Failed to send notification: {e}") from e
