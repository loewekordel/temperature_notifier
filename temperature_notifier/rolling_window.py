"""
This module defines a rolling window for temperature data.
"""

import logging
from collections import deque
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Deque
from typing import Self

logger = logging.getLogger(__name__)


@dataclass
class RollingWindowEntry:
    """
    Represents an entry in the rolling window.

    :param time: The timestamp of the entry.
    :param temperature: The temperature value.
    """

    time: datetime
    temperature: float


class RollingWindow:
    """Rolling window for temperature data."""

    def __init__(self, window_minutes: int):
        """
        Initializes the rolling window.

        :param window_minutes: The time span (in minutes) for the rolling window.
        """
        self.window_minutes = window_minutes
        self.entries: Deque[RollingWindowEntry] = deque()

    def __repr__(self) -> str:
        """
        Returns a debug-friendly string representation of the RollingWindow.
        """
        return (
            f"RollingWindow(window_minutes={self.window_minutes}, "
            f"entries={self.entries} entries)"
        )

    def append(self, current_time: datetime, temperature: float) -> None:
        """
        Appends a new entry to the rolling window and
        removes entries older than the specified window.

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
        self, rise_threshold: float, drop_threshold: float
    ) -> bool:
        """
        Checks if there is a significant rise followed by a significant drop
        in temperature within the rolling window.

        :param rise_threshold: The threshold for significant rise.
        :param drop_threshold: The threshold for significant drop.
        :return: True if such an event is detected, False otherwise.
        """
        if not self.entries or len(self.entries) < 3:
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

        # 2. Find the minimum value before the maximum (the "rise" valley)
        if max_index == 0:
            return False
        min_before_max = min(
            entry.temperature for entry in list(self.entries)[:max_index]
        )

        # 3. Look for the minimum value after the maximum (the "drop" valley)
        if max_index == len(self.entries) - 1:
            return False
        min_after_max = min(
            entry.temperature for entry in list(self.entries)[max_index + 1 :]
        )

        rise = max_value - min_before_max
        drop = max_value - min_after_max
        logger.info(f"Rise: {rise:.2f}, Drop: {drop:.2f}")

        return rise >= rise_threshold and drop >= drop_threshold

    def has_significant_rise(self, threshold: float) -> bool:
        """
        Checks if there is a significant rise in temperature within the rolling window.

        :param threshold: The threshold for significant rise.
        :return: True if a significant rise is detected, False otherwise.
        """
        if not self.entries:
            return False
        # Not enough entries to compare
        if len(self.entries) < 2:
            return False

        logger.info(
            "Rolling window entries:\n%s",
            "\n".join(
                f"         {entry.time.strftime('%Y-%m-%d %H:%M:%S')} | {entry.temperature:.2f}°C"
                for entry in self.entries
            ),
        )
        # Find the maximum value and its index
        max_index, max_entry = max(
            enumerate(self.entries), key=lambda x: x[1].temperature
        )
        max_value = max_entry.temperature  # Extract the temperature value

        # Loop backward to find the minimum value before the maximum
        min_value = max_value  # Initialize to max_value
        for i in range(max_index, -1, -1):
            min_value = min(min_value, self.entries[i].temperature)
        logger.info(f"Max value: {max_value}, Min value: {min_value}")

        # Calculate the difference and check if it exceeds the threshold
        return (max_value - min_value) >= threshold

    def is_within_window(self, timestamp: datetime) -> bool:
        """
        Checks if a given timestamp is within the time span of the rolling window.

        :param timestamp: The timestamp to check.
        :return: True if the timestamp is within the rolling window, False otherwise.
        """
        if not self.entries:
            return False  # No entries in the rolling window

        return self.entries[0].time <= timestamp <= self.entries[-1].time

    def to_dict(self) -> list[dict]:
        """
        Serializes the rolling window to a list of dictionaries.

        :return: A list of dictionaries representing the rolling window.
        """
        return [asdict(entry) for entry in self.entries]

    @classmethod
    def from_dict(cls, data: list[dict], window_minutes: int) -> Self:
        """
        Deserializes a list of dictionaries into a RollingWindow object.

        :param data: A list of dictionaries representing the rolling window.
        :param window_minutes: The time span (in minutes) for the rolling window.
        :return: A RollingWindow object.
        """
        instance = cls(window_minutes)
        instance.entries = deque(
            RollingWindowEntry(
                time=datetime.fromisoformat(entry["time"]),
                temperature=entry["temperature"],
            )
            for entry in data
        )
        return instance
