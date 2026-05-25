"""Rolling window for temperature data."""

import itertools
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Self

logger = logging.getLogger(__name__)

_MIN_WINDOW_ENTRIES = 3


class TemperatureTrend(Enum):
    """Direction of the outdoor temperature trend over recent rolling window entries."""

    COOLING = "cooling"
    WARMING = "warming"
    UNKNOWN = "unknown"


@dataclass
class RollingWindowEntry:
    """Represents an entry in the rolling window.

    :param time: The timestamp of the entry.
    :param temperature: The temperature value.
    """

    time: datetime
    temperature: float


class RollingWindow:
    """Rolling window for temperature data."""

    def __init__(self, window_minutes: int):
        """Initialize the rolling window.

        :param window_minutes: The time span (in minutes) for the rolling window.
        """
        self.window_minutes = window_minutes
        self.entries: deque[RollingWindowEntry] = deque()

    def __repr__(self) -> str:
        """Return a debug-friendly string representation of the RollingWindow."""
        return (
            f"RollingWindow(window_minutes={self.window_minutes}, "
            f"entries={len(self.entries)} entries)"
        )

    def append(self, current_time: datetime, temperature: float) -> None:
        """Append a new entry to the rolling window.

        Removes entries older than the configured window span.

        :param current_time: The current timestamp.
        :param temperature: The temperature to add to the rolling window.
        """
        self.entries.append(
            RollingWindowEntry(time=current_time, temperature=temperature)
        )
        cutoff_time = current_time - timedelta(minutes=self.window_minutes)
        while self.entries and self.entries[0].time < cutoff_time:
            self.entries.popleft()

    def has_significant_rise_and_drop(
        self, rise_threshold: float, drop_threshold: float, min_peak_temperature: float | None = None
    ) -> bool:
        """Check for a significant rise followed by a significant drop within the window.

        Optionally requires the peak to have exceeded ``min_peak_temperature`` (e.g. indoor
        temperature), so the event only counts when outdoor was genuinely warmer than indoor —
        indicating a real "missed window" opportunity rather than a minor outdoor fluctuation.

        :param rise_threshold: The threshold for significant rise.
        :param drop_threshold: The threshold for significant drop.
        :param min_peak_temperature: If set, the peak temperature must exceed this value.
        :return: True if such an event is detected, False otherwise.
        """
        if not self.entries or len(self.entries) < _MIN_WINDOW_ENTRIES:
            return False

        logger.info(
            "Rolling window entries:\n%s",
            "\n".join(
                f"         {entry.time.strftime('%Y-%m-%d %H:%M:%S')}: {entry.temperature:.2f}°C"
                for entry in self.entries
            ),
        )

        # 1. Find the maximum value and its index (the "rise" peak)
        max_index, max_entry = max(
            enumerate(self.entries), key=lambda x: x[1].temperature
        )
        max_value = max_entry.temperature

        # 2. Require the peak to have exceeded indoor temperature so that only a genuine
        #    warm-then-cool reversal (outdoor was above indoor) triggers the event.
        if min_peak_temperature is not None and max_value < min_peak_temperature:
            logger.info(
                f"Peak outdoor temperature ({max_value:.2f}°C) did not exceed indoor temperature "
                f"({min_peak_temperature:.2f}°C). No rapid change event."
            )
            return False

        # 3. Find the minimum value before the maximum (the "rise" valley)
        if max_index == 0:
            return False
        min_before_max = min(e.temperature for e in itertools.islice(self.entries, max_index))

        # 4. Look for the minimum value after the maximum (the "drop" valley)
        if max_index == len(self.entries) - 1:
            return False
        min_after_max = min(e.temperature for e in itertools.islice(self.entries, max_index + 1, None))

        rise = max_value - min_before_max
        drop = max_value - min_after_max
        logger.info(f"Rise: {rise:.2f}, Drop: {drop:.2f}")

        return rise >= rise_threshold and drop >= drop_threshold

    def temperature_trend(self, num_entries: int = 3) -> TemperatureTrend:
        """Determine the outdoor temperature trend over the last num_entries readings.

        Compares the most recent entry against the entry num_entries positions back.
        Returns UNKNOWN when not enough entries exist to determine a trend.

        :param num_entries: Number of recent entries to span the trend check.
        :return: COOLING, WARMING, or UNKNOWN.
        """
        if len(self.entries) < num_entries:
            return TemperatureTrend.UNKNOWN
        if self.entries[-1].temperature < self.entries[-num_entries].temperature:
            return TemperatureTrend.COOLING
        return TemperatureTrend.WARMING

    def is_timestamp_within_window(self, timestamp: datetime) -> bool:
        """Check if a given timestamp is within the time span of the rolling window.

        :param timestamp: The timestamp to check.
        :return: True if the timestamp is within the rolling window, False otherwise.
        """
        if not self.entries:
            return False

        return self.entries[0].time <= timestamp <= self.entries[-1].time

    def to_dict(self) -> list[dict]:
        """Serialize the rolling window to a list of dictionaries.

        :return: A list of dictionaries representing the rolling window.
        """
        return [asdict(entry) for entry in self.entries]

    @classmethod
    def from_dict(cls, data: list[dict], window_minutes: int) -> Self:
        """Deserialize a list of dictionaries into a RollingWindow object.

        :param data: A list of dictionaries representing the rolling window.
        :param window_minutes: The time span (in minutes) for the rolling window.
        :return: A RollingWindow object.
        """
        instance = cls(window_minutes)
        instance.entries = deque(
            RollingWindowEntry(time=datetime.fromisoformat(entry["time"]), temperature=entry["temperature"])
            for entry in data
        )
        return instance
