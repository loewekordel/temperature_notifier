"""Configuration module for the temperature notifier application.

Defines the configuration classes and functions to load the configuration from a YAML file.
"""

import logging
from dataclasses import dataclass
from datetime import time
from pathlib import Path

import jsonschema
import yaml

from temperature_notifier.notifiers import Notifier, SimplePushNotifier

logger = logging.getLogger(__name__)

_MAX_PORT = 65535

# Define the configuration schema using JSON Schem
TEMPERATURE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "field": {"type": "string"},
    },
    "required": ["name", "field"],
    "additionalProperties": False,
}

INFLUXDB_SCHEMA = {
    "type": "object",
    "properties": {
        "host": {"type": "string"},
        "port": {"type": "integer"},
        "database": {"type": "string"},
        "max_data_age_minutes": {"type": "integer", "minimum": 1},
        "measurements": {
            "type": "object",
            "properties": {
                "indoor": TEMPERATURE_SCHEMA,
                "outdoor": TEMPERATURE_SCHEMA,
            },
            "required": ["indoor", "outdoor"],
            "additionalProperties": False,
        },
    },
    "required": ["host", "port", "database", "max_data_age_minutes", "measurements"],
    "additionalProperties": False,
}

SIMPLEPUSH_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"const": "simplepush"},
        "key": {"type": "string"},
    },
    "required": ["type", "key"],
    "additionalProperties": False,
}

NOTIFIER_SCHEMA = {
    "type": "array",
    "items": {
        "oneOf": [
            SIMPLEPUSH_SCHEMA,
        ]
    },
    "minItems": 1,
}

RAPID_CHANGE_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "rise": {"type": "number"},
        "drop": {"type": "number"},
        "window_minutes": {"type": "number"},
        "min_peak_temperature": {"type": "number"},
    },
    "required": ["rise", "drop", "window_minutes"],
    "additionalProperties": False,
}

REENABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "cooldown_minutes": {"type": "number", "minimum": 0},
        "min_rise_between_notifications": {"type": "number", "minimum": 0},
    },
    "required": ["cooldown_minutes", "min_rise_between_notifications"],
    "additionalProperties": False,
}

NOTIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "min_indoor_temperature": {"type": "number"},
        "rapid_change_event": RAPID_CHANGE_EVENT_SCHEMA,
        "reenable": REENABLE_SCHEMA,
    },
    "required": ["min_indoor_temperature", "rapid_change_event", "reenable"],
    "additionalProperties": False,
}

ARMING_SCHEMA = {
    "type": "object",
    "properties": {
        "temperature_delta": {"type": "number"},
        "time": {
            "type": "string",
            "pattern": "^(?:[01]\\d|2[0-3]):[0-5]\\d$",  # Matches "HH:MM" 24-hour format
        },
    },
    "anyOf": [{"required": ["temperature_delta"]}, {"required": ["time"]}],
    "additionalProperties": False,
}

CONFIGURATION_SCHEMA = {
    "type": "object",
    "properties": {
        "influxdb": INFLUXDB_SCHEMA,
        "notifiers": NOTIFIER_SCHEMA,
        "notification": NOTIFICATION_SCHEMA,
        "arming": ARMING_SCHEMA,
    },
    "required": ["influxdb", "notifiers", "notification", "arming"],
    "additionalProperties": False,
}


class ConfigurationError(Exception):
    """Custom exception for configuration errors."""


@dataclass
class MeasurementConfiguration:
    """Configuration for a measurement.

    :var name: The name of the measurement.
    :var field: The field name in the measurement.
    """

    name: str
    field: str


@dataclass
class MeasurementsConfiguration:
    """Configuration for measurements.

    :var indoor: Configuration for indoor measurement.
    :var outdoor: Configuration for outdoor measurement.
    """

    indoor: MeasurementConfiguration
    outdoor: MeasurementConfiguration


@dataclass
class InfluxDBConfiguration:
    """Configuration for InfluxDB connection.

    :var host: The InfluxDB host.
    :var port: The InfluxDB port.
    :var database: The InfluxDB database name.
    :var max_data_age_minutes: Maximum age of a data point before it is considered stale.
    :var measurements: Configuration for measurements.
    """

    host: str
    port: int
    database: str
    max_data_age_minutes: int
    measurements: MeasurementsConfiguration


# Mapping of notifier types to their configuration classes
notifier_class_lookup: dict[str, type] = {}


def register_notifier_config(type_value: str):
    """Decorator to register a notifier configuration class.

    :var type_value: The type value for the notifier, used as a key in the lookup.
    :return: The decorator function.
    """

    def decorator(cls):
        """Decorator function to register the class.

        :param cls: The class to register
        :return: The class itself.
        """
        notifier_class_lookup[type_value.lower()] = cls
        return cls

    return decorator


@register_notifier_config("simplepush")
@dataclass
class SimplePushConfiguration:
    """Configuration for SimplePush.

    :var key: The SimplePush API key.
    """

    key: str

    def create_notifier(self) -> Notifier:
        """Creates a SimplePushNotifier instance based on the configuration.

        :return: An instance of SimplePushNotifier.
        """
        return SimplePushNotifier(key=self.key)


# Extend as Union[SimplePushConfiguration, ...] when more notifier types are added
NotifierConfiguration = SimplePushConfiguration


@dataclass
class RapidChangeEventConfiguration:
    """Configuration for rapid change event.

    :var rise: The temperature rise threshold to trigger a rapid change event notification.
    :var drop: The temperature drop threshold to trigger a rapid change event notification.
    :var window_minutes: The time window in minutes to consider for rapid change events.
    :var min_peak_temperature: Minimum outdoor peak temperature (°C) required for the event
        to fire. When omitted, the current indoor temperature is used as the threshold.
    """

    rise: float
    drop: float
    window_minutes: int
    min_peak_temperature: float | None = None


@dataclass
class ReenableConfiguration:
    """Configuration for re-enabling notifications after cooldown.

    :var cooldown_minutes: The time to wait before re-enabling notifications.
    :var min_rise_between_notifications: The minimum temperature rise required to trigger a notification.
    """

    cooldown_minutes: int
    min_rise_between_notifications: float


@dataclass
class NotificationConfiguration:
    """Configuration for notifications.

    :var min_indoor_temperature: The minimum indoor temperature to trigger notifications.
    :var rapid_change_event: Configuration for rapid change events.
    :var reenable: Configuration for re-enabling notifications after cooldown.
    :var stale_warning_cooldown_minutes: Cooldown between stale-data warning notifications.
    """

    min_indoor_temperature: float
    rapid_change_event: RapidChangeEventConfiguration
    reenable: ReenableConfiguration


@dataclass
class ArmingConfiguration:
    """Configuration for arming the notifier.

    :var temperature_delta: The temperature difference required to arm the notifier.
    :var arming_time: The time of day to arm the notifier (optional).
    """

    temperature_delta: float | None = None
    arming_time: time | None = None


@dataclass
class Configuration:
    """Top level configuration.

    :var influxdb: InfluxDB configuration object.
    :var notifiers: List of notifier configurations.
    :var notification: Configuration for notifications.
    :var arming: Configuration for arming the notifier.
    """

    influxdb: InfluxDBConfiguration
    notifiers: list[NotifierConfiguration]
    notification: NotificationConfiguration
    arming: ArmingConfiguration


def load_configuration_from_file(config_file: Path) -> Configuration:
    """Loads the configuration from a YAML file and returns a Configuration object.

    :param file_path: Path to the YAML configuration file.
    :return: Configuration object with InfluxDB and SimplePush settings.
    :raises ConfigurationError: If the file is not found or if there are parsing errors.
    """
    logger.debug(f"Loading configuration from '{config_file}'...")

    try:
        with open(config_file) as f:
            data = yaml.safe_load(f)

        # Validate the configuration against the schema
        try:
            jsonschema.validate(instance=data, schema=CONFIGURATION_SCHEMA)
        except jsonschema.ValidationError as e:
            raise ConfigurationError(
                f"Configuration validation error: {e.message}\n"
                f"Schema ["
                f"{'.'.join(map(str, list(e.schema_path)[1:-1]))}]:\n"
                f"{e.schema}\n"
                f"Instance:\n{e.instance}"
            ) from e

        # Parse the measurements
        measurements = MeasurementsConfiguration(
            indoor=MeasurementConfiguration(**data["influxdb"]["measurements"]["indoor"]),
            outdoor=MeasurementConfiguration(**data["influxdb"]["measurements"]["outdoor"]),
        )

        # Parse notifiers
        notifiers = []
        for notifier_data in data.get("notifiers", []):
            # Validate notifier type
            notifier_type = notifier_data["type"].lower()
            notifier_class = notifier_class_lookup.get(notifier_type)
            if notifier_class is None:
                raise ConfigurationError(f"Unknown notifier type: {notifier_type}")
            # Remove 'type' from kwargs to avoid passing it to the notifier class since it's not a parameter
            kwargs = {k: v for k, v in notifier_data.items() if k != "type"}
            # Create notifier instance
            notifiers.append(notifier_class(**kwargs))

        # Parse notification configuration
        notification = NotificationConfiguration(
            min_indoor_temperature=data["notification"]["min_indoor_temperature"],
            rapid_change_event=RapidChangeEventConfiguration(
                rise=data["notification"]["rapid_change_event"]["rise"],
                drop=data["notification"]["rapid_change_event"]["drop"],
                window_minutes=data["notification"]["rapid_change_event"]["window_minutes"],
                min_peak_temperature=data["notification"]["rapid_change_event"].get("min_peak_temperature"),
            ),
            reenable=ReenableConfiguration(
                cooldown_minutes=data["notification"]["reenable"]["cooldown_minutes"],
                min_rise_between_notifications=data["notification"]["reenable"]["min_rise_between_notifications"],
            ),
        )

        # Parse arming configuration
        arming_data = data.get("arming", {})
        # Parse the arming time if provided
        arming_time_str = arming_data.get("time")
        arming_time = None
        if arming_time_str:
            try:
                hours, minutes = map(int, arming_time_str.split(":"))
                arming_time = time(hour=hours, minute=minutes)
            except Exception as e:
                raise ConfigurationError(f"Invalid arming.time format: '{arming_time_str}'. Expected 'HH:MM'.") from e
        # Parse the arming temperature delta if provided
        arming_temperature_delta = arming_data.get("temperature_delta", None)

        # Validate the configuration values
        if not 1 <= data["influxdb"]["port"] <= _MAX_PORT:
            raise ConfigurationError("Invalid port number in InfluxDB configuration.")

        # Create and return the Configuration object
        return Configuration(
            influxdb=InfluxDBConfiguration(
                host=data["influxdb"]["host"],
                port=data["influxdb"]["port"],
                database=data["influxdb"]["database"],
                max_data_age_minutes=data["influxdb"]["max_data_age_minutes"],
                measurements=measurements,
            ),
            notifiers=notifiers,
            notification=notification,
            arming=ArmingConfiguration(
                temperature_delta=arming_temperature_delta,
                arming_time=arming_time,
            ),
        )
    except FileNotFoundError as e:
        raise ConfigurationError(e) from e
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Failed to parse configuration file: {e}") from e
    except KeyError as e:
        raise ConfigurationError(f"Missing configuration key: {e}") from e
