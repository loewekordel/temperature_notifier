"""Temperature data provider package."""

from abc import ABC, abstractmethod


class TemperatureSource(ABC):
    """Abstract source for temperature readings."""

    @abstractmethod
    def get_last_value(self, name: str, field: str, max_age_minutes: int | None = None) -> float | None:
        """Return the most recent value for the given measurement.

        :param name: Measurement name.
        :param field: Field name within the measurement.
        :param max_age_minutes: If set, only return data newer than this many minutes.
        :return: The last value, or None if unavailable or stale.
        """
