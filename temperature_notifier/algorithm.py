"""Algorithm for comparing indoor and outdoor temperatures.

Sends notifications based on configured thresholds and conditions.

Three distinct paths can trigger a notification:

  1. Initial cooling — first notification of the day. A trend check prevents spurious
     alerts when outdoor temperature is still rising and only briefly dips below indoor.

  2. Rapid change re-notification — a short-duration weather reversal (e.g. thunderstorm)
     where outdoor temperature peaked above indoor and then dropped back within the rolling
     window. The notification timer is reset immediately without waiting for a cooldown.

  3. Slow cycle re-notification — a longer warm period (e.g. hot afternoon) where outdoor
     exceeded indoor for longer than the rolling window. Re-notification is allowed after
     the cooldown has passed and outdoor has risen sufficiently since the last alert.
"""

import logging
from datetime import datetime

from temperature_notifier.configuration import Configuration
from temperature_notifier.influxdb_service import InfluxDBService
from temperature_notifier.notifiers import Notifier
from temperature_notifier.rolling_window import TemperatureTrend
from temperature_notifier.state_manager import StateManager

logger = logging.getLogger(__name__)


def _reset_daily_state_if_new_day(state_manager: StateManager, current_datetime: datetime) -> None:
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


def _should_arm(
    state_manager: StateManager,
    config: Configuration,
    current_datetime: datetime,
) -> bool:
    """Determine if the notifier should arm based on the configured arming time.

    :param state_manager: The state manager instance.
    :param config: The configuration instance.
    :param current_datetime: The current datetime.
    :return: True if the notifier should arm now, False otherwise.
    """
    if state_manager.state.armed:
        logger.info("Notifier is already armed. No action taken.")
        return False

    if current_datetime.time() >= config.arming.arming_time:
        logger.info(
            f"Arming notifier: current time ({current_datetime.strftime('%H:%M')}) "
            f">= arming time ({config.arming.arming_time.strftime('%H:%M')})"
        )
        return True

    logger.info(
        f"Notifier not armed: current time ({current_datetime.strftime('%H:%M')}) "
        f"is before arming time ({config.arming.arming_time.strftime('%H:%M')})"
    )
    return False


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


def _handle_initial_cooling(
    state_manager: StateManager,
    config: Configuration,
    notifiers: list[Notifier],
    current_datetime: datetime,
    indoor_temp: float,
    outdoor_temp: float,
) -> None:
    """Notification path 1: first notification of the day.

    Uses the rolling window trend to distinguish a genuine cooling event from a brief dip
    while outdoor temperature is still rising (e.g. early morning):

    - COOLING: outdoor is on a downward trend — notify as soon as outdoor < indoor.
    - WARMING / UNKNOWN: outdoor is rising or trend cannot be determined — only notify if
      outdoor is at least min_temperature_difference °C below indoor, guarding against
      spurious alerts when outdoor barely crosses below indoor before climbing again.

    :param state_manager: State manager instance.
    :param config: Configuration instance.
    :param notifiers: List of notifier instances.
    :param current_datetime: Current datetime.
    :param indoor_temp: Current indoor temperature.
    :param outdoor_temp: Current outdoor temperature.
    """
    logger.info("No notification sent today — checking initial cooling conditions...")
    trend = state_manager.state.rolling_window.temperature_trend()

    if trend == TemperatureTrend.COOLING:
        logger.info(f"Outdoor trend: {trend.value}. Notifying if outdoor < indoor.")
        if outdoor_temp < indoor_temp:
            _send_temperature_alert(notifiers, state_manager, current_datetime, indoor_temp, outdoor_temp)
        else:
            logger.info("Outdoor is not yet below indoor. No notification sent.")
        return

    min_diff = config.notification.min_temperature_difference
    if trend == TemperatureTrend.UNKNOWN:
        logger.info(f"Outdoor trend: {trend.value} (insufficient data). Requiring delta >= {min_diff}°C.")
    else:
        logger.info(f"Outdoor trend: {trend.value}. Requiring delta >= {min_diff}°C.")

    if indoor_temp - outdoor_temp >= min_diff:
        _send_temperature_alert(notifiers, state_manager, current_datetime, indoor_temp, outdoor_temp)
    else:
        logger.info(
            f"Outdoor is not {min_diff}°C below indoor "
            f"(delta={indoor_temp - outdoor_temp:.2f}°C). No notification sent."
        )


def _is_notification_reset_by_rapid_change(
    state_manager: StateManager,
    config: Configuration,
    current_datetime: datetime,
    indoor_temp: float,
) -> bool:
    """Notification path 2: rapid change event re-notification.

    Targets short-duration weather reversals — typically a fast-moving thunderstorm — where
    outdoor temperature rises sharply above indoor (windows should close) and then drops back
    below indoor (windows should re-open) within the rolling window (``window_minutes``).
    When detected, the notification timer is reset immediately so a new alert can fire without
    waiting for the cooldown or min-rise guards.

    The outdoor peak must have exceeded the current indoor temperature; a fluctuation that
    stayed below indoor the whole time does not represent a missed window opportunity and is
    therefore ignored.

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


def _handle_slow_cycle_renotification(
    state_manager: StateManager,
    config: Configuration,
    notifiers: list[Notifier],
    current_datetime: datetime,
    indoor_temp: float,
    outdoor_temp: float,
) -> None:
    """Notification path 3: slow cycle re-notification.

    Handles two cases that share the same final send step:

    - After a rapid change event (path 2) reset the notification timer, ``last_notification_time``
      is None and the cooldown / min-rise guards are skipped — the alert fires immediately if
      outdoor < indoor.
    - After a slow warm period (e.g. hot afternoon) the guards are evaluated: both the cooldown
      and a minimum outdoor temperature rise must be satisfied before a new alert is sent.

    :param state_manager: State manager instance.
    :param config: Configuration instance.
    :param notifiers: List of notifier instances.
    :param current_datetime: Current datetime.
    :param indoor_temp: Current indoor temperature.
    :param outdoor_temp: Current outdoor temperature.
    """
    if state_manager.state.last_notification_time is not None:
        logger.info("Checking slow-cycle re-notification conditions...")
        if state_manager.is_notification_in_cooldown(current_datetime, config.notification.reenable.cooldown_minutes):
            logger.info("Notification is in cooldown period. No notification sent.")
            return
        min_rise = config.notification.reenable.min_rise_between_notifications
        if not state_manager.has_min_rise_since_last_notification(min_rise):
            logger.info(f"Insufficient temperature rise ({min_rise}°C) since last notification. No notification sent.")
            return

    logger.info("Comparing outdoor and indoor temperatures...")
    if outdoor_temp < indoor_temp:
        _send_temperature_alert(notifiers, state_manager, current_datetime, indoor_temp, outdoor_temp)


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
    _reset_daily_state_if_new_day(state_manager, current_datetime)

    logger.info("Fetching indoor and outdoor temperatures from InfluxDB...")
    max_age = config.influxdb.max_data_age_minutes
    indoor_temp = influxdb_service.get_last_value(config.influxdb.measurements.indoor, max_age_minutes=max_age)
    outdoor_temp = influxdb_service.get_last_value(config.influxdb.measurements.outdoor, max_age_minutes=max_age)

    if indoor_temp is None or outdoor_temp is None:
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
    if _should_arm(state_manager, config, current_datetime):
        state_manager.set_armed(True)
        state_manager.save_state()

    if not state_manager.is_armed():
        logger.info("Notifier is not armed. No notification sent.")
        return

    # Path 1 — initial cooling: first notification of the day
    if state_manager.state.last_notification_time is None:
        _handle_initial_cooling(state_manager, config, notifiers, current_datetime, indoor_temp, outdoor_temp)
        return

    # Path 2 — rapid change event: short-duration weather reversal within rolling window
    if _is_notification_reset_by_rapid_change(state_manager, config, current_datetime, indoor_temp):
        return

    # Path 3 — slow cycle / post-rapid-change send
    _handle_slow_cycle_renotification(state_manager, config, notifiers, current_datetime, indoor_temp, outdoor_temp)
