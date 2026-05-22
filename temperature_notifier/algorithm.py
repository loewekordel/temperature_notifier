"""
This module contains the main algorithm for comparing indoor and outdoor temperatures,
and sending notifications based on the configured thresholds and conditions.
"""

import logging
from datetime import datetime


from temperature_notifier.configuration import Configuration
from temperature_notifier.influxdb_service import InfluxDBService
from temperature_notifier.notifiers import Notifier
from temperature_notifier.state_manager import StateManager

logger = logging.getLogger(__name__)


def is_indoor_temp_below_threshold(
    min_indoor_temperature: float,
    indoor_temp: float,
) -> bool:
    """
    Checks if the indoor temperature is below the configured threshold.

    :param config: The configuration instance.
    :param indoor_temp: The current indoor temperature.
    :return: True if the indoor temperature is below the threshold, False otherwise.
    """
    return indoor_temp <= min_indoor_temperature


def should_arm(
    state_manager: StateManager,
    config: Configuration,
    indoor_temp: float,
    outdoor_temp: float,
    current_datetime: datetime,
) -> bool:
    """
    Determines if the system should be armed based on the temperature difference or
    a configured start time.

    :param state_manager: The state manager instance.
    :param config: The configuration instance.
    :param indoor_temp: The current indoor temperature.
    :param outdoor_temp: The current outdoor temperature.
    :param current_datetime: The current datetime.
    :return: True if the system should be armed, False otherwise.
    """
    arm_by_temp = False
    arm_by_time = False

    if config.arming.temperature_delta is None and config.arming.time is None:
        logger.warning(
            "Neither arming termperture delta nor arming time is set in the configuration."
        )
        return False

    # Check temperature delta arming
    if config.arming.temperature_delta is not None:
        arm_by_temp = indoor_temp - outdoor_temp >= config.arming.temperature_delta

    # Check time arming
    if config.arming.time is not None:
        current_time = current_datetime.time()
        arm_by_time = current_time >= config.arming.time

    # When both conditions are configured, require both (AND) so that time acts as a
    # hard gate — temperature delta alone cannot arm before the configured time.
    # When only one condition is configured, that single condition is sufficient.
    both_configured = config.arming.temperature_delta is not None and config.arming.time is not None
    should_arm_now = (arm_by_temp and arm_by_time) if both_configured else (arm_by_temp or arm_by_time)

    if not state_manager.state.armed and should_arm_now:
        reasons = []
        if arm_by_temp:
            reasons.append(
                f"indoor_temp ({indoor_temp}°C) - outdoor_temp ({outdoor_temp}°C) >= temperature_delta ({config.arming.temperature_delta}°C)"
            )
        if arm_by_time:
            reasons.append(
                f"current time ({current_datetime.time().strftime('%H:%M')}) >= arming time ({config.arming.time.strftime('%H:%M')})"
            )
        logger.info(f"Arming notifier because: {'; '.join(reasons)}")
        return True

    # Log why the notifier is not armed
    if state_manager.state.armed:
        logger.info("Notifier is already armed. No action taken.")
    else:
        logger.info(
            f"Notifier not armed: arm_by_temp={arm_by_temp}, arm_by_time={arm_by_time}"
        )

    return False


def compare_temperatures(
    config: Configuration,
    influxdb_service: InfluxDBService,
    state_manager: StateManager,
    notifiers: list[Notifier],
) -> None:
    """
    Compares temperatures and sends notifications if conditions are met.

    This function checks the indoor and outdoor temperatures, determines if the notifier should be armed,
    and sends notifications based on the configured thresholds and conditions.

    :param config: The configuration instance.
    :param influxdb_service: The InfluxDB service instance to fetch temperature data.
    :param state_manager: The state manager instance to manage the notifier state.
    :param notifiers: List of notifier instances to send notifications.
    :raises InfluxDBServiceError: If there is an error fetching temperature data from InfluxDB.
    :raises NotifierError: If there is an error sending notifications.
    :raises StateManagerError: If there is an error managing the state.
    """
    current_datetime = datetime.now()

    # Check if a new day has started and reset the state if necessary
    logger.info("Checking for new day...")
    if state_manager.is_new_day(current_datetime):
        logger.info("New day detected. Resetting state.")
        state_manager.reset_daily_state()
        state_manager.state.last_run_date = current_datetime.date()
        state_manager.save_state()
    else:
        logger.info("No new day detected. Continuing with current state.")
        state_manager.state.last_run_date = current_datetime.date()

    # Get temperatures for indoor and outdoor
    logger.info("Fetching indoor and outdoor temperatures from InfluxDB...")
    max_age = config.influxdb.max_data_age_minutes
    indoor_temp = influxdb_service.get_last_value(config.influxdb.measurements.indoor, max_age_minutes=max_age)
    outdoor_temp = influxdb_service.get_last_value(config.influxdb.measurements.outdoor, max_age_minutes=max_age)

    if indoor_temp is None or outdoor_temp is None:
        # check which sensors are stale
        stale_sensors = []
        if indoor_temp is None:
            stale_sensors.append(f"indoor ({config.influxdb.measurements.indoor.name})")
        if outdoor_temp is None:
            stale_sensors.append(f"outdoor ({config.influxdb.measurements.outdoor.name})")
        stale_msg = ", ".join(stale_sensors)
        logger.warning(f"Stale or missing data for sensors: {stale_msg}")

        # Check if a stale data warning has already been sent today or if it's before the arming time
        if state_manager.is_stale_warning_sent_today(current_datetime):
            logger.info("Stale data warning already sent today, skipping notification.")
        elif config.arming.time is not None and current_datetime.time() < config.arming.time:
            logger.info(
                f"Stale data detected but before arming time ({config.arming.time.strftime('%H:%M')}), skipping notification."
            )
        else:
            logger.info("Sending stale data warning notification.")
            for notifier in notifiers:
                notifier.send_notification(
                    "Sensor Data Warning",
                    f"No recent data (>{max_age} min) for sensor(s): {stale_msg}. Temperature monitoring paused.",
                )
            state_manager.state.last_stale_warning_time = current_datetime
            state_manager.save_state()
        return

    logger.info(
        f"Indoor temperature: {indoor_temp}°C, Outdoor temperature: {outdoor_temp}°C"
    )

    # Update rolling window
    logger.debug(f"Updating rolling window and temps since last notification...")
    state_manager.state.rolling_window.append(current_datetime, outdoor_temp)
    state_manager.state.temps_since_last_notification.append(outdoor_temp)
    state_manager.save_state()
    logger.debug("Rolling window and temps updated.")

    # Check if indoor temperature is below the threshold
    logger.info("Checking if indoor temperature is below the threshold...")
    if is_indoor_temp_below_threshold(
        config.notification.min_indoor_temperature, indoor_temp
    ):
        logger.info(
            (
                f"Indoor temperature ({indoor_temp}°C) is below the threshold ({config.notification.min_indoor_temperature:}°C). "
                "No notification sent."
            )
        )
        return
    else:
        logger.info(
            f"Indoor temperature ({indoor_temp}°C) is above the threshold ({config.notification.min_indoor_temperature}°C). Proceeding with notification checks."
        )

    # Arm the notifier if conditions are met
    logger.info("Checking if notifier should be armed...")
    if should_arm(state_manager, config, indoor_temp, outdoor_temp, current_datetime):
        state_manager.set_armed(True)
        state_manager.save_state()

    # Check for significant rapid change event
    logger.info("Checking for a rapid change event...")
    if state_manager.has_rolling_window_rapid_change_event(
        config.notification.rapid_change_event.rise,
        config.notification.rapid_change_event.drop,
    ):
        # Check if the last notification is still within the rolling window
        if state_manager.is_last_notification_within_rolling_window():
            logger.info(
                (
                    "Rapid change event already notified and still within the rolling window. "
                    "No notification sent."
                )
            )
            return

        logger.info(
            "Rapid change event detected. Resetting last notification time."
        )
        state_manager.state.last_significant_rise_time = current_datetime
        state_manager.reset_notification_time()
        state_manager.save_state()
    else:
        logger.info("No Rapid change event detected.")

    # Check if the notification shall be reenabled
    if state_manager.state.last_notification_time is not None:
        # Check if notification is in cooldown period
        logger.info("Checking if notification is in cooldown period...")
        if state_manager.is_notification_in_cooldown(
            current_datetime, config.notification.reenable.cooldown_minutes
        ):
            logger.info("Notification is in cooldown period. No notification sent.")
            return

        # Check if there was a sufficient temperature rise since last notification
        logger.info("Checking if there was a sufficient temperature rise since last notification...")
        min_rise = config.notification.reenable.min_rise_between_notifications
        if not state_manager.has_min_rise_since_last_notification(min_rise):
            logger.info(
                f"No sufficient temperature rise ({min_rise}°C) since last notification. No notification sent."
            )
            return
    else:
        logger.info("No notification has been sent today. Skipping cooldown and rise checks.")

    if not state_manager.is_armed():
        logger.info("Notifier is not armed. No notification sent.")
        return

    # Check if outdoor temperature is lower than indoor temperature
    logger.info("Comparing outdoor and indoor temperatures...")
    if outdoor_temp < indoor_temp:
        logger.info(
            "Outdoor temperature is lower than indoor temperature. Sending notification."
        )
        for notifier in notifiers:
            notifier.send_notification(
                "Temperature Alert",
                f"Outdoor temperature is lower than indoor temperature! {outdoor_temp}°C < {indoor_temp}°C",
            )
        state_manager.state.last_notification_time = current_datetime
        state_manager.state.temps_since_last_notification.clear()
        state_manager.save_state()
