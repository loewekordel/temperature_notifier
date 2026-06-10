"""Home Assistant notifier implementation."""

import logging

import requests

from temperature_notifier.notifications import Notification, StaleSensorNotification, TemperatureNotification
from temperature_notifier.notifiers.base import Notifier, NotifierError

logger = logging.getLogger(__name__)


class HomeAssistantNotifier(Notifier):
    """Notifier that delivers notifications via the Home Assistant REST API."""

    def __init__(self, url: str, token: str, service: str) -> None:
        """Initialize the HomeAssistantNotifier.

        :param url: Base URL of the Home Assistant instance (e.g. 'http://homeassistant.local:8123').
        :param token: Long-lived access token.
        :param service: HA service path as 'domain/service' (e.g. 'notify/mobile_app_my_phone').
        """
        self._url = url.rstrip("/")
        self._token = token
        self._service = service

    def send(self, notification: Notification) -> None:
        """Send a notification via the Home Assistant REST API.

        :param notification: The notification to send.
        :raises NotifierError: If sending the notification fails.
        """
        if isinstance(notification, TemperatureNotification):
            title = "Temperature Alert"
            message = f"Outdoor {notification.outdoor_temp}°C < indoor {notification.indoor_temp}°C"
        elif isinstance(notification, StaleSensorNotification):
            title = "Sensor Data Warning"
            message = (
                f"No recent data (>{notification.max_age_minutes} min) for sensor(s): {notification.sensors}. "
                "Temperature monitoring paused."
            )
        else:
            raise NotifierError(f"Unsupported notification type: {type(notification)}")

        endpoint = f"{self._url}/api/services/{self._service}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        payload = {"title": title, "message": message}

        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info("Home Assistant notification sent successfully.")
        except requests.HTTPError as e:
            raise NotifierError(f"Home Assistant API error {e.response.status_code}: {e.response.text}") from e
        except requests.RequestException as e:
            raise NotifierError(f"Network error sending Home Assistant notification: {e}") from e
