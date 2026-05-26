"""Base classes for notifiers."""

from abc import ABC, abstractmethod

from temperature_notifier.notifications import Notification


class NotifierError(Exception):
    """Custom exception for Notifier errors."""


class Notifier(ABC):
    """Abstract base class for sending notifications."""

    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Send a notification.

        :param notification: The notification to send.
        """
