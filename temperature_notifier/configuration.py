"""Configuration module for the temperature notifier application.

Defines the configuration models and the function to load configuration from a YAML file.
"""

import logging
from datetime import time
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from temperature_notifier.notifiers import Notifier, SimplePushNotifier

logger = logging.getLogger(__name__)

_MAX_PORT = 65535


class MeasurementConfiguration(BaseModel):
    """InfluxDB measurement name and field."""

    name: str
    field: str


class MeasurementsConfiguration(BaseModel):
    """Indoor and outdoor measurement configuration."""

    indoor: MeasurementConfiguration
    outdoor: MeasurementConfiguration


class InfluxDBConfiguration(BaseModel):
    """InfluxDB connection and measurement configuration."""

    host: str
    port: int = Field(ge=1, le=_MAX_PORT)
    database: str
    max_data_age_minutes: int = Field(ge=1)
    measurements: MeasurementsConfiguration


class SimplePushConfiguration(BaseModel):
    """Configuration for the SimplePush notifier."""

    type: str
    key: str

    def create_notifier(self) -> Notifier:
        """Create a SimplePushNotifier from this configuration."""
        return SimplePushNotifier(key=self.key)


class RapidChangeEventConfiguration(BaseModel):
    """Configuration for rapid outdoor temperature change detection."""

    rise: float
    drop: float
    window_minutes: int
    min_peak_temperature: float | None = None


class ReenableConfiguration(BaseModel):
    """Configuration for re-enabling notifications after a cooldown."""

    cooldown_minutes: int = Field(ge=0)
    min_rise_between_notifications: float = Field(ge=0)


class NotificationConfiguration(BaseModel):
    """Notification thresholds and re-enable settings."""

    min_indoor_temperature: float
    rapid_change_event: RapidChangeEventConfiguration
    reenable: ReenableConfiguration


class ArmingConfiguration(BaseModel):
    """Conditions that must be met before the notifier arms itself."""

    temperature_delta: float | None = None
    arming_time: time | None = Field(default=None, alias="time")

    @field_validator("arming_time", mode="before")
    @classmethod
    def parse_time(cls, v: str | time | None) -> time | None:
        """Parse an 'HH:MM' string into a time object."""
        if v is None or isinstance(v, time):
            return v
        try:
            hours, minutes = map(int, v.split(":"))
            return time(hour=hours, minute=minutes)
        except Exception as e:
            raise ValueError(f"Invalid time format '{v}'. Expected 'HH:MM'.") from e

    @model_validator(mode="after")
    def at_least_one_arming_condition(self) -> "ArmingConfiguration":
        """Require at least one of temperature_delta or arming_time to be set."""
        if self.temperature_delta is None and self.arming_time is None:
            raise ValueError("At least one of 'temperature_delta' or 'time' must be set in arming configuration.")
        return self


class Configuration(BaseModel):
    """Top-level configuration."""

    influxdb: InfluxDBConfiguration
    notifiers: list[SimplePushConfiguration] = Field(min_length=1)
    notification: NotificationConfiguration
    arming: ArmingConfiguration


class ConfigurationError(Exception):
    """Raised when the configuration file cannot be loaded or is invalid."""


def load_configuration_from_file(config_file: Path) -> Configuration:
    """Load and validate configuration from a YAML file.

    :param config_file: Path to the YAML configuration file.
    :return: Validated Configuration object.
    :raises ConfigurationError: If the file is missing, unparseable, or invalid.
    """
    logger.debug(f"Loading configuration from '{config_file}'...")
    try:
        with open(config_file) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigurationError(e) from e
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Failed to parse configuration file: {e}") from e

    try:
        return Configuration.model_validate(data)
    except Exception as e:
        raise ConfigurationError(f"Configuration validation error: {e}") from e
