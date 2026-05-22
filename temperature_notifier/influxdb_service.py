"""
InfluxDBService module.
This module provides a service to interact with InfluxDB.
"""

import logging

from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError

from .configuration import MeasurementConfiguration

logger = logging.getLogger(__name__)


class InfluxDBServiceError(Exception):
    """Custom exception for InfluxDBService errors."""


class InfluxDBService:
    """Service to interact with InfluxDB."""

    def __init__(self, host: str, port: int) -> None:
        """
        Initializes the InfluxDB client and connects to the specified database.
        """
        self.client = InfluxDBClient(host=host, port=port)

    def switch_database(self, database: str) -> None:
        """
        Switches to the specified database.

        :param database: The name of the database to switch to.
        """
        self.client.switch_database(database)

    def get_last_value(
        self, measurement: MeasurementConfiguration, max_age_minutes: int | None = None
    ) -> float | None:
        """
        Queries the last value from a given measurement.

        :param measurement: The measurement configuration containing the name and field.
        :param max_age_minutes: If set, only returns data newer than this many minutes.
                                Returns None (and logs a warning) when data is older.
        :return: The last value from the specified measurement, or None if unavailable/stale.
        """
        try:
            query = f'SELECT LAST("{measurement.field}") FROM "{measurement.name}"'
            if max_age_minutes is not None:
                query += f" WHERE time > now() - {max_age_minutes}m"
            result = self.client.query(query)
            points = list(result.get_points())
            if not points:
                logger.warning(
                    f"No recent data for measurement '{measurement.name}' field '{measurement.field}'"
                    + (f" (within last {max_age_minutes} min)" if max_age_minutes else "") + "."
                )
                return None
            return points[0]["last"]
        except (InfluxDBClientError, ValueError) as e:
            raise InfluxDBServiceError(
                f"Failed to query InfluxDB for measurement '{measurement.name}': {e}"
            ) from e
