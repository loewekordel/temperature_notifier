"""Notification data classes for the temperature notifier."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Notification:
    """Base class for all notification types."""


@dataclass(frozen=True)
class TemperatureNotification(Notification):
    """Emitted when outdoor temperature drops below indoor temperature.

    :param indoor_temp: Current indoor temperature in °C.
    :param outdoor_temp: Current outdoor temperature in °C.
    """

    indoor_temp: float
    outdoor_temp: float


@dataclass(frozen=True)
class StaleSensorNotification(Notification):
    """Emitted when one or more sensors have not reported recent data.

    :param sensors: Comma-separated list of stale sensor names.
    :param max_age_minutes: Configured maximum data age in minutes.
    """

    sensors: str
    max_age_minutes: int
