"""Algorithm for comparing indoor and outdoor temperatures.

Sends notifications based on configured thresholds and conditions.
"""

import logging
from datetime import datetime

from temperature_notifier.configuration import Configuration
from temperature_notifier.influxdb_service import InfluxDBService
from temperature_notifier.notifiers import Notifier
from temperature_notifier.state_manager import StateManager

logger = logging.getLogger(__name__)


def _should_arm(
    state_manager: StateManager,
    config: Configuration,
    indoor_temp: float,
    outdoor_temp: float,
    current_datetime: datetime,
) -> bool:
    """Determines if the system should be armed based on the temperature difference or a configured start time.

    :param state_manager: The state manager instance.
    :param config: The configuration instance.
    :param indoor_temp: The current indoor temperature.
    :param outdoor_temp: The current outdoor temperature.
    :param current_datetime: The current datetime.
    :return: True if the system should be armed, False otherwise.
    """
    arm_by_temp = False
    arm_by_time = False

    if config.arming.temperature_delta is None and config.arming.arming_time is None:
        logger.warning("Neither arming temperature delta nor arming time is set in the configuration.")
        return False

    # Check temperature delta arming
    if config.arming.temperature_delta is not None:
        arm_by_temp = indoor_temp - outdoor_temp >= config.arming.temperature_delta

    # Check time arming
    if config.arming.arming_time is not None:
        current_time = current_datetime.time()
        arm_by_time = current_time >= config.arming.arming_time

    # When both conditions are configured, require both (AND) so that time acts as a
    # hard gate — temperature delta alone cannot arm before the configured time.
    # When only one condition is configured, that single condition is sufficient.
    both_configured = config.arming.temperature_delta is not None and config.arming.arming_time is not None
    should_arm_now = (arm_by_temp and arm_by_time) if both_configured else (arm_by_temp or arm_by_time)

    if not state_manager.state.armed and should_arm_now:
        reasons = []
        if arm_by_temp:
            reasons.append(
                f"indoor_temp ({indoor_temp}°C) - outdoor_temp ({outdoor_temp}°C) "
                f">= temperature_delta ({config.arming.temperature_delta}°C)"
            )
        if arm_by_time:
            reasons.append(
                f"current time ({current_datetime.time().strftime('%H:%M')}) "
                f">= arming time ({config.arming.arming_time.strftime('%H:%M')})"
            )
        logger.info(f"Arming notifier because: {'; '.join(reasons)}")
        return True

    # Log why the notifier is not armed
    if state_manager.state.armed:
        logger.info("Notifier is already armed. No action taken.")
    else:
        logger.info(f"Notifier not armed: arm_by_temp={arm_by_temp}, arm_by_time={arm_by_time}")

    return False


def _maybe_reset_daily_state(state_manager: StateManager, current_datetime: datetime) -> None:
    """Reset daily state if a new day has started, then record today's date.

    :param state_manager: State manager instance.
    :param current_datetime: Current datetime.
    """
    logger.info("Checking for new day...")
    if state_manager.is_new_day(current_datetime):
        logger.info("New day detected. Resetting state.")
        state_manager.reset_daily_state()
    else:
        logger.info("No new day detected. Continuing with current state.")
    state_manager.state.last_run_date = current_datetime.date()
    state_manager.save_state()


def _handle_stale_sensors(
    state_manager: StateManager,
    config: Configuration,
    notifiers: list[Notifier],
    current_datetime: datetime,
    stale_msg: str,
) -> None:
    """Notify about stale/missing sensor data if not already done today.

    :param state_manager: State manager instance.
    :param config: Configuration instance.
    :param notifiers: List of notifier instances.
    :param current_datetime: Current datetime.
    :param stale_msg: Comma-separated list of stale sensor names.
    """
    max_age = config.influxdb.max_data_age_minutes
    logger.warning(f"Stale or missing data for sensors: {stale_msg}")

    if state_manager.is_stale_warning_sent_today(current_datetime):
        logger.info("Stale data warning already sent today, skipping notification.")
        return

    if config.arming.arming_time is not None and current_datetime.time() < config.arming.arming_time:
        logger.info(
            f"Stale data detected but before arming time ({config.arming.arming_time.strftime('%H:%M')}), "
            "skipping notification."
        )
        return

    logger.info("Sending stale data warning notification.")
    for notifier in notifiers:
        notifier.send_notification(
            "Sensor Data Warning",
            f"No recent data (>{max_age} min) for sensor(s): {stale_msg}. Temperature monitoring paused.",
        )
    state_manager.state.last_stale_warning_time = current_datetime
    state_manager.save_state()


def _is_notification_reset_by_rapid_change(
    state_manager: StateManager,
    config: Configuration,
    current_datetime: datetime,
    indoor_temp: float,
) -> bool:
    """Check for a rapid change event and reset the notification timer if one is found.

    Targets short-duration weather reversals — typically a fast-moving thunderstorm — where
    outdoor temperature rises sharply above indoor (windows should close) and then drops back
    below indoor (windows should re-open) within the rolling window (``window_minutes``).
    When detected, the notification timer is reset immediately so a new alert can fire without
    waiting for the cooldown or min-rise guards.

    The outdoor peak must have exceeded the current indoor temperature; a fluctuation that
    stayed below indoor the whole time does not represent a missed window opportunity and is
    therefore ignored.

    Contrast with the min-rise / cooldown path (see ``_is_notification_blocked``), which
    handles slower weather cycles where the warm period lasts longer than the rolling window.

    :param state_manager: State manager instance.
    :param config: Configuration instance.
    :param current_datetime: Current datetime.
    :param indoor_temp: Current indoor temperature used as the minimum peak threshold.
    :return: True if a rapid change event was detected and already handled (caller should abort).
    """
    min_peak = config.notification.rapid_change_event.min_peak_temperature
    if min_peak is None:
        min_peak = indoor_temp

    logger.info("Checking for a rapid change event...")
    if not state_manager.has_rolling_window_rapid_change_event(
        config.notification.rapid_change_event.rise,
        config.notification.rapid_change_event.drop,
        min_peak_temperature=min_peak,
    ):
        logger.info("No rapid change event detected.")
        return False

    if state_manager.is_last_notification_within_rolling_window():
        logger.info("Rapid change event already notified and still within the rolling window. No notification sent.")
        return True

    logger.info("Rapid change event detected. Resetting last notification time.")
    state_manager.state.last_significant_rise_time = current_datetime
    state_manager.reset_notification_time()
    state_manager.save_state()
    return False


def _send_temperature_alert(
    notifiers: list[Notifier],
    state_manager: StateManager,
    current_datetime: datetime,
    indoor_temp: float,
    outdoor_temp: float,
) -> None:
    """Send temperature alert to all notifiers and update state.

    :param notifiers: List of notifier instances.
    :param state_manager: State manager instance.
    :param current_datetime: Current datetime.
    :param indoor_temp: Current indoor temperature.
    :param outdoor_temp: Current outdoor temperature.
    """
    logger.info("Outdoor temperature is lower than indoor temperature. Sending notification.")
    for notifier in notifiers:
        notifier.send_notification(
            "Temperature Alert",
            f"Outdoor temperature is lower than indoor temperature! {outdoor_temp}°C < {indoor_temp}°C",
        )
    state_manager.state.last_notification_time = current_datetime
    state_manager.state.temps_since_last_notification.clear()
    state_manager.save_state()


def _is_notification_blocked(
    state_manager: StateManager,
    config: Configuration,
    current_datetime: datetime,
) -> bool:
    """Check cooldown and minimum-rise guards that block re-notification.

    Targets slower weather cycles — e.g. a thunderstorm whose warm build-up phase lasts
    several hours — where the outdoor temperature gradually climbs above indoor over a period
    longer than the rolling window, then cools back down.  In such cases the rapid change
    event (see ``_handle_rapid_change``) never fires because the rise and subsequent drop do
    not both fit inside the rolling window.  Instead, this guard allows a new notification
    once two conditions are jointly satisfied:

    1. The cooldown period (``cooldown_minutes``) has elapsed since the last notification.
    2. Outdoor temperature has risen by at least ``min_rise_between_notifications`` °C at
       some point since the last notification, confirming a meaningful warm period occurred.

    On a monotonically cooling evening neither condition is likely to be met, so in practice
    only one notification fires per evening unless the weather reverses.

    :param state_manager: State manager instance.
    :param config: Configuration instance.
    :param current_datetime: Current datetime.
    :return: True if notification should be suppressed.
    """
    if state_manager.state.last_notification_time is None:
        logger.info("No notification has been sent today. Skipping cooldown and rise checks.")
        return False

    logger.info("Checking if notification is in cooldown period...")
    if state_manager.is_notification_in_cooldown(current_datetime, config.notification.reenable.cooldown_minutes):
        logger.info("Notification is in cooldown period. No notification sent.")
        return True

    logger.info("Checking if there was a sufficient temperature rise since last notification...")
    min_rise = config.notification.reenable.min_rise_between_notifications
    if not state_manager.has_min_rise_since_last_notification(min_rise):
        logger.info(f"No sufficient temperature rise ({min_rise}°C) since last notification. No notification sent.")
        return True

    return False


def compare_temperatures(
    config: Configuration,
    influxdb_service: InfluxDBService,
    state_manager: StateManager,
    notifiers: list[Notifier],
) -> None:
    """Compare temperatures and send a notification when outdoor < indoor.

    :param config: The configuration instance.
    :param influxdb_service: The InfluxDB service instance to fetch temperature data.
    :param state_manager: The state manager instance to manage the notifier state.
    :param notifiers: List of notifier instances to send notifications.
    :raises InfluxDBServiceError: If there is an error fetching temperature data from InfluxDB.
    :raises NotifierError: If there is an error sending notifications.
    :raises StateManagerError: If there is an error managing the state.
    """
    current_datetime = datetime.now()
    _maybe_reset_daily_state(state_manager, current_datetime)

    logger.info("Fetching indoor and outdoor temperatures from InfluxDB...")
    max_age = config.influxdb.max_data_age_minutes
    indoor_temp = influxdb_service.get_last_value(config.influxdb.measurements.indoor, max_age_minutes=max_age)
    outdoor_temp = influxdb_service.get_last_value(config.influxdb.measurements.outdoor, max_age_minutes=max_age)

    if indoor_temp is None or outdoor_temp is None:
        # Build a human-readable list of which sensors have stale/missing data
        stale_sensors = []
        if indoor_temp is None:
            stale_sensors.append(f"indoor ({config.influxdb.measurements.indoor.name})")
        if outdoor_temp is None:
            stale_sensors.append(f"outdoor ({config.influxdb.measurements.outdoor.name})")
        _handle_stale_sensors(state_manager, config, notifiers, current_datetime, ", ".join(stale_sensors))
        return

    logger.info(f"Indoor temperature: {indoor_temp}°C, Outdoor temperature: {outdoor_temp}°C")

    logger.debug("Updating rolling window and temps since last notification...")
    state_manager.state.rolling_window.append(current_datetime, outdoor_temp)
    state_manager.state.temps_since_last_notification.append(outdoor_temp)
    state_manager.save_state()

    logger.info("Checking if indoor temperature is below the threshold...")
    if indoor_temp <= config.notification.min_indoor_temperature:
        logger.info(
            f"Indoor temperature ({indoor_temp}°C) is below the threshold "
            f"({config.notification.min_indoor_temperature}°C). No notification sent."
        )
        return
    logger.info(
        f"Indoor temperature ({indoor_temp}°C) is above the threshold "
        f"({config.notification.min_indoor_temperature}°C). Proceeding with notification checks."
    )

    logger.info("Checking if notifier should be armed...")
    if _should_arm(state_manager, config, indoor_temp, outdoor_temp, current_datetime):
        state_manager.set_armed(True)
        state_manager.save_state()

    if not state_manager.is_armed():
        logger.info("Notifier is not armed. No notification sent.")
        return

    if _is_notification_reset_by_rapid_change(state_manager, config, current_datetime, indoor_temp):
        return

    if _is_notification_blocked(state_manager, config, current_datetime):
        return

    logger.info("Comparing outdoor and indoor temperatures...")
    if outdoor_temp < indoor_temp:
        _send_temperature_alert(notifiers, state_manager, current_datetime, indoor_temp, outdoor_temp)
