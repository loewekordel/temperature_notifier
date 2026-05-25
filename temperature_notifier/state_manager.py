"""State management for the temperature notifier application."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .rolling_window import RollingWindow

logger = logging.getLogger(__name__)

_MIN_TEMPS_FOR_RISE = 2


def serialize_datetime(dt: datetime) -> str:
    """Serialize a datetime object to an ISO-format string.

    :param dt: The datetime object to serialize.
    :return: The serialized datetime string.
    """
    return dt.isoformat() if dt else None


def deserialize_datetime(dt_str: str) -> datetime:
    """Deserialize an ISO-format string to a datetime object.

    :param dt_str: The string to deserialize.
    :return: The deserialized datetime object.
    """
    return datetime.fromisoformat(dt_str) if dt_str else None


@dataclass
class State:
    """Represent the runtime state of the temperature notifier.

    :param last_notification_time: The time of the last notification sent.
    :param last_significant_rise_time: The time of the last significant-rise notification.
    :param last_stale_warning_time: The time of the last stale-data warning notification.
    :param armed: Whether the temperature notifier is armed to send notifications.
    :param rolling_window: Rolling window of recent outdoor temperatures.
    """

    last_notification_time: datetime | None = None
    last_significant_rise_time: datetime | None = None
    last_stale_warning_time: datetime | None = None
    last_run_date: date | None = None
    armed: bool = False
    rolling_window: RollingWindow | None = None
    temps_since_last_notification: list[float] = field(default_factory=list)


class StateManagerError(Exception):
    """Custom exception for StateManager errors."""


class StateManager:
    """Manage persistent state for the temperature notifier."""

    def __init__(self, state_file: Path, rolling_window_minutes: int) -> None:
        """Initialize the StateManager with the path to the state file.

        :param state_file: The path to the state file.
        :param rolling_window_minutes: Time span (in minutes) for the rolling window.
        """
        self.state_file = state_file
        self.state = State(rolling_window=RollingWindow(rolling_window_minutes))
        self.load_state()

    def __repr__(self) -> str:
        """Return a debug-friendly string representation of the StateManager."""
        return f"StateManager(state_file={self.state_file!r}, state={self.state!r})"

    def load_state(self) -> None:
        """Load the state from a file."""
        if self.state_file.exists():
            logger.debug(f"Loading state from '{self.state_file}'...")

            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                    # Restore all state fields from the persisted dict
                    self.state.last_notification_time = deserialize_datetime(
                        data.get("last_notification_time")
                    )
                    self.state.last_significant_rise_time = deserialize_datetime(
                        data.get("last_significant_rise_time")
                    )
                    self.state.last_stale_warning_time = deserialize_datetime(
                        data.get("last_stale_warning_time")
                    )
                    last_run_date_str = data.get("last_run_date")
                    self.state.last_run_date = date.fromisoformat(last_run_date_str) if last_run_date_str else None
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
            except OSError as e:
                raise StateManagerError(f"Failed to read state file: {e}") from e

    def save_state(self) -> None:
        """Save the state to a file."""
        logger.debug(f"Saving state to '{self.state_file}'")

        try:
            state_dict = {
                "last_notification_time": serialize_datetime(self.state.last_notification_time),
                "last_significant_rise_time": serialize_datetime(self.state.last_significant_rise_time),
                "last_stale_warning_time": serialize_datetime(self.state.last_stale_warning_time),
                "last_run_date": self.state.last_run_date.isoformat() if self.state.last_run_date else None,
                "armed": self.state.armed,
                "rolling_window": [
                    {"time": serialize_datetime(entry.time), "temperature": entry.temperature}
                    for entry in self.state.rolling_window.entries
                ],
                "temps_since_last_notification": self.state.temps_since_last_notification,
            }
            with open(self.state_file, "w") as f:
                json.dump(state_dict, f, indent=4)
            logger.debug("State saved successfully.")
        except OSError as e:
            logger.warning(f"Failed to write state file: {e}")

    def is_new_day(self, current_datetime: datetime) -> bool:
        """Check if a new day has started based on the last run date.

        :param current_datetime: The current time to compare against the last run date.
        :return: True if a new day has started, False otherwise.
        """
        if self.state.last_run_date is not None:
            return self.state.last_run_date != current_datetime.date()
        return False

    def is_armed(self) -> bool:
        """Check if the notifier is armed.

        :return: True if the notifier is armed, False otherwise.
        """
        return self.state.armed

    def set_armed(self, armed: bool) -> None:
        """Set the armed state of the notifier.

        :param armed: Whether the notifier should be armed.
        """
        self.state.armed = armed
        logger.info(f"Notifier armed state set to {armed}.")

    def reset_notification_time(self) -> None:
        """Reset the notification time to allow a new notification."""
        self.state.last_notification_time = None
        logger.info("Notification time reset.")

    def reset_daily_state(self) -> None:
        """Reset all daily state: armed flag, notification times, and temps buffer.

        Called at the start of each new day.
        """
        self.state.last_notification_time = None
        self.state.last_significant_rise_time = None
        self.state.last_stale_warning_time = None
        self.state.armed = False
        self.state.temps_since_last_notification = []
        logger.info("Daily state reset: armed=False, notification times cleared, temps cleared.")

    def is_notification_in_cooldown(
        self, current_datetime: datetime, cooldown_minutes: int
    ) -> bool:
        """Check if the notification is in a cooldown period.

        :param current_datetime: The current time to compare against the last notification time.
        :param cooldown_minutes: The cooldown period in minutes after a notification is sent.
        :return: True if the notification is in cooldown, False otherwise.
        """
        last_time = self.state.last_notification_time
        if last_time is None:
            return False
        elapsed_minutes = int((current_datetime - last_time).total_seconds() / 60)
        # Log remaining cooldown time to help with debugging notification suppression
        if elapsed_minutes < cooldown_minutes:
            logger.debug(
                f"Last notification was {elapsed_minutes} minutes ago, "
                f"cooldown is {cooldown_minutes} minutes."
            )
            return True
        return False

    def has_rolling_window_rapid_change_event(
        self,
        temperature_rise: float,
        temperature_drop: float,
        min_peak_temperature: float | None = None,
    ) -> bool:
        """Check for a rapid temperature change event within the rolling window.

        :param temperature_rise: Rise threshold to trigger a rapid change event.
        :param temperature_drop: Drop threshold to trigger a rapid change event.
        :param min_peak_temperature: If set, the outdoor peak must have exceeded this value
            (typically the current indoor temperature) so the event only fires when outdoor
            was genuinely warmer than indoor.
        :return: True if there is a rapid change event, False otherwise.
        """
        return self.state.rolling_window.has_significant_rise_and_drop(
            temperature_rise,
            temperature_drop,
            min_peak_temperature,
        )

    def is_last_notification_within_rolling_window(self) -> bool:
        """Check if the last significant-rise notification is still within the rolling window.

        :return: True if the last notification time is within the rolling window, False otherwise.
        """
        if not self.state.last_significant_rise_time:
            logger.debug("No last significant rise time set, cannot check rolling window.")
            return False

        return self.state.rolling_window.is_timestamp_within_window(
            self.state.last_significant_rise_time
        )

    def is_stale_warning_sent_today(self, current_datetime: datetime) -> bool:
        """Check if a stale-data warning has already been sent today.

        :param current_datetime: The current datetime.
        :return: True if a stale warning was already sent today, False otherwise.
        """
        if self.state.last_stale_warning_time is None:
            return False
        return self.state.last_stale_warning_time.date() == current_datetime.date()

    def has_min_rise_since_last_notification(self, min_rise: float) -> bool:
        """Check if there has been a minimum temperature rise since the last notification.

        :param min_rise: The minimum temperature rise required to trigger a notification.
        :return: True if there has been a sufficient rise, False otherwise.
        """
        temps = self.state.temps_since_last_notification
        if len(temps) < _MIN_TEMPS_FOR_RISE:
            return False

        # Walk through recorded temperatures tracking the running minimum.
        # Return True as soon as any later reading exceeds the minimum by at least min_rise.
        min_temp = temps[0]
        for temp in temps[1:]:
            if temp - min_temp >= min_rise:
                logger.debug(
                    f"Detected temperature rise: {temp:.2f}°C - {min_temp:.2f}°C"
                    f" = {temp - min_temp:.2f}°C >= {min_rise:.2f}°C"
                )
                return True
            # Keep the lowest value seen so far as the baseline for the next rise check
            min_temp = min(min_temp, temp)

        logger.debug(f"No significant rise detected in temperatures since last notification: {temps}")
        return False
