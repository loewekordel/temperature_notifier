"""
This module defines the state management for the temperature notifier application.
"""

import json
import logging
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from .rolling_window import RollingWindow


logger = logging.getLogger(__name__)


def serialize_datetime(dt: datetime) -> str:
    """
    Serializes a datetime object to a string in ISO format.

    :param datetime dt: The datetime object to serialize.
    :return str: The serialized datetime string.
    """
    return dt.isoformat() if dt else None


def deserialize_datetime(dt_str: str) -> datetime:
    """
    Deserializes a string in ISO format to a datetime object.

    :param str dt_str: The string to deserialize.
    :return datetime: The deserialized datetime object.
    """
    return datetime.fromisoformat(dt_str) if dt_str else None


@dataclass
class State:
    """
    Represents the state of the application.

    :param last_notification_time: The time of the last notification sent.
    :param last_significant_rise_time: The time of the last notification sent for a significant temperature rise.
    :param armed: Whether the temperature notifier is armed to send notifications.
    :param rolling_window: Serialized representation of the rolling window.
    """

    last_notification_time: datetime = None
    last_significant_rise_time: datetime = None
    armed: bool = False
    rolling_window: RollingWindow | None = None
    temps_since_last_notification: list[float] = field(default_factory=list)


class StateManagerError(Exception):
    """Custom exception for StateManager errors."""


class StateManager:
    """Top-level class for managing the state of the application."""

    def __init__(self, state_file: Path, rolling_window_minutes: int) -> None:
        """
        Initializes the StateManager with the path to the state file.

        :param state_file: The path to the state file.
        :param rolling_window_minutes: The time span (in hours) for the rolling window.
        """
        self.state_file = state_file
        self.state = State(rolling_window=RollingWindow(rolling_window_minutes))
        self.load_state()

    def __repr__(self) -> str:
        """
        Returns a debug-friendly string representation of the StateManager.
        """
        return f"StateManager(state_file={self.state_file!r}, state={self.state!r}, "

    def load_state(self) -> None:
        """Load the state from a file."""

        if self.state_file.exists():
            logger.debug(f"Loading state from '{self.state_file}'...")

            # Attempt to read the state file
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    # Update the dataclass attributes from the loaded state
                    self.state.last_notification_time = deserialize_datetime(
                        data.get("last_notification_time")
                    )
                    self.state.last_significant_rise_time = deserialize_datetime(
                        data.get("last_significant_rise_time")
                    )
                    self.state.armed = data.get("armed", False)
                    self.state.rolling_window = RollingWindow.from_dict(
                        data.get("rolling_window", []),
                        window_minutes=self.state.rolling_window.window_minutes,
                    )
                    self.state.temps_since_last_notification = data.get(
                        "temps_since_last_notification", []
                    )
                    logger.debug("State loaded successfully.")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse state file: {e}")
            except (OSError, IOError) as e:
                raise StateManagerError(f"Failed to read state file: {e}") from e

    def save_state(self) -> None:
        """Save the state to a file."""
        logger.debug(f"Saving state to '{self.state_file}'")

        try:
            # Convert the dataclass to a dictionary for serialization
            state_to_save = asdict(self.state)
            # Convert datetime objects to strings for serialization
            state_to_save["last_notification_time"] = serialize_datetime(
                state_to_save["last_notification_time"]
            )
            state_to_save["last_significant_rise_time"] = serialize_datetime(
                state_to_save["last_significant_rise_time"]
            )
            # Include the armed state
            state_to_save["armed"] = self.state.armed
            # Serialize the rolling window entries
            state_to_save["rolling_window"] = [
                {
                    "time": serialize_datetime(entry.time),
                    "temperature": entry.temperature,
                }
                for entry in self.state.rolling_window.entries
            ]
            # Include temperatures since the last notification
            state_to_save["temps_since_last_notification"] = (
                self.state.temps_since_last_notification
            )
            # Write the state to the file
            with open(self.state_file, "w") as f:
                json.dump(state_to_save, f, indent=4)
                logger.debug("State saved successfully.")
        except (OSError, IOError) as e:
            logger.warning(f"Failed to write state file: {e}")

    def is_new_day(self, current_datetime: datetime) -> bool:
        """
        Checks if a new day has started based on the last notification time.

        :param current_datetime: The current time to compare against the last notification time.
        :return: True if a new day has started, False otherwise.
        """
        if self.state.last_notification_time:
            last_notification_date = self.state.last_notification_time.date()
            if last_notification_date != current_datetime.date():
                return True
        return False

    def is_notification_sent_today(
        self,
        current_datetime: datetime,
    ) -> bool:
        """
        Checks if a notification has already been sent today.

        :param current_datetime: The current time to compare against the last notification time.
        :return: True if a notification has been sent today, False otherwise.
        """
        if self.state.last_notification_time:
            return self.state.last_notification_time.date() == current_datetime.date()

        return False

    def is_armed(self) -> bool:
        """
        Checks if the notifier is armed.

        :return: True if the notifier is armed, False otherwise.
        """
        return self.state.armed

    def set_armed(self, armed: bool) -> None:
        """
        Sets the armed state of the notifier.

        :param armed: Whether the notifier should be armed.
        """
        self.state.armed = armed
        logger.info(f"Notifier armed state set to {armed}.")

    def reset_notification_time(self) -> None:
        """
        Resets the notification time to allow a new notification.
        """
        self.state.last_notification_time = None
        logger.info("Notification time reset.")

    def is_notification_in_cooldown(
        self, current_datetime: datetime, cooldown_minutes: int
    ) -> bool:
        """
        Checks if the notification is in a cooldown period based on the last notification time.

        :param current_datetime: The current time to compare against the last notification time.
        :param cooldown_minutes: The cooldown period in minutes after a notification is sent.
        :return: True if the notification is in cooldown, False otherwise.
        """
        last_time = self.state.last_notification_time
        if last_time is None:
            return False
        # log how many minutes are left in the cooldown
        if (current_datetime - last_time) < timedelta(minutes=cooldown_minutes):
            logger.debug(
                f"Last notification was {int((current_datetime - last_time).total_seconds() / 60)} minutes ago, cooldown is {cooldown_minutes} minutes."
            )
            return True
        else:
            return False

    # def is_significant_rise(
    #     self,
    #     temperature_rise: float,
    # ) -> bool:
    #     """
    #     Checks if there is a significant temperature rise based on the rolling window.

    #     :param temperature_rise: The temperature rise to check against the rolling window.
    #     :return: True if there is a significant rise, False otherwise.
    #     """
    #     return self.state.rolling_window.has_significant_rise(temperature_rise)

    def has_rolling_window_rapid_change_event(
        self,
        temperature_rise: float,
        temperature_drop: float,
    ) -> bool:
        """
        Checks if there is a rapid change event in temperature
        within the rolling window.

        :param state_manager: The state manager instance.
        :param config: The configuration instance.
        :return: True if there is a rapid change event, False otherwise.
        """
        return self.state.rolling_window.has_significant_rise_and_drop(
            temperature_rise,
            temperature_drop,
        )

    def is_last_notification_within_rolling_window(self) -> bool:
        """
        Checks if the last notification time is within the rolling window.

        :param last_notification_time: The time of the last notification.
        :return: True if the last notification time is within the rolling window, False otherwise.
        """
        # Check if the last significant rise notification is still in the rolling window
        if not self.state.last_significant_rise_time:
            logger.debug(
                "No last significant rise time set, cannot check rolling window."
            )
            return False

        return self.state.rolling_window.is_within_window(
            self.state.last_significant_rise_time
        )

    def has_min_rise_since_last_notification(self, min_rise: float) -> bool:
        """
        Checks if there has been a minimum temperature rise since the last notification.

        :param min_rise: The minimum temperature rise required to trigger a notification.
        :return: True if there has been a sufficient rise, False otherwise.
        """
        temps = self.state.temps_since_last_notification
        if len(temps) < 2:
            return False

        # iterate through the temperatures and find the minimum temperature
        # # then check if the difference between the current temperature and the minimum
        # temperature is greater than or equal to the minimum rise
        min_temp = temps[0]
        for temp in temps[1:]:
            # Check if the current temperature minus the minimum temperature
            # is greater than or equal to the minimum rise
            if temp - min_temp >= min_rise:
                logger.debug(
                    f"Detected temperature rise: {temp:.2f}°C - {min_temp:.2f}°C = {temp - min_temp:.2f}°C >= {min_rise:.2f}°C"
                )
                return True

            # Update the minimum temperature if the current temperature is lower
            min_temp = min(min_temp, temp)

        logger.debug(
            f"No significant rise detected in temperatures since last notification: {temps}"
        )
        return False
