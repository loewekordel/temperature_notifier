"""SimplePush notifier implementation."""

import logging

import requests
from simplepush import (
    BadRequest,
    RateLimitExceeded,
    UnknownError,
    send as send_simplepush,
)

from temperature_notifier.notifications import Notification, StaleSensorNotification, TemperatureNotification
from temperature_notifier.notifiers.base import Notifier, NotifierError

logger = logging.getLogger(__name__)


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
        except RateLimitExceeded:
            raise NotifierError("SimplePush rate limit exceeded") from None
        except BadRequest:
            raise NotifierError("SimplePush rejected the message (title or message too long)") from None
        except UnknownError:
            raise NotifierError("SimplePush returned an unexpected status") from None
        except ValueError as e:
            raise NotifierError(f"SimplePush returned a non-JSON response: {e}") from e
        except requests.RequestException as e:
            raise NotifierError(f"Network error sending SimplePush notification: {e}") from e
        except Exception as e:
            raise NotifierError(f"Failed to send notification: {e}") from e
