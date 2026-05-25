"""Notifier classes for sending push notifications."""

import logging
from abc import ABC, abstractmethod

from simplepush import send as send_simplepush

from temperature_notifier.notifications import Notification, StaleSensorNotification, TemperatureNotification

logger = logging.getLogger(__name__)


class NotifierError(Exception):
    """Custom exception for Notifier errors."""


class Notifier(ABC):
    """Abstract base class for sending notifications."""

    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Send a notification.

        :param notification: The notification to send.
        """


class SimplePushNotifier(Notifier):
    """Notifier that delivers notifications via the SimplePush service."""

    def __init__(self, key: str) -> None:
        """Initialize the SimplePushNotifier with the provided SimplePush key.

        :param key: The SimplePush key for sending notifications.
        """
        self.key = key

    def send(self, notification: Notification) -> None:
        """Send a notification via SimplePush.

        :param notification: The notification to send.
        :raises NotifierError: If sending the notification fails.
        """
        try:
            if isinstance(notification, TemperatureNotification):
                send_simplepush(
                    self.key,
                    f"Outdoor {notification.outdoor_temp}°C < indoor {notification.indoor_temp}°C",
                    "Temperature Alert",
                )
            elif isinstance(notification, StaleSensorNotification):
                send_simplepush(
                    self.key,
                    f"No recent data (>{notification.max_age_minutes} min) for sensor(s): {notification.sensors}. "
                    "Temperature monitoring paused.",
                    "Sensor Data Warning",
                )
            else:
                raise NotifierError(f"Unsupported notification type: {type(notification)}")
            logger.info("Notification sent successfully.")
        except NotifierError:
            raise
        except Exception as e:
            raise NotifierError(f"Failed to send notification: {e}") from e
