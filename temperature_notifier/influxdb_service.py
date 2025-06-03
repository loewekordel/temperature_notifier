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

    def get_last_value(self, measurement: MeasurementConfiguration) -> float | None:
        """
        Queries the last value value from a given measurement.

        :param measurement: The measurement configuration containing the name and field.
        :return: The last value from the specified measurement.
        """
        try:
            query = f'SELECT LAST("{measurement.field}") FROM "{measurement.name}"'
            result = self.client.query(query)
            points = list(result.get_points())
            if not points:
                logger.warning(
                    f"No data found for measurement '{measurement.name}' in field '{measurement.field}'."
                )
                return None
            return points[0]["last"]
        except (InfluxDBClientError, ValueError) as e:
            raise InfluxDBServiceError(
                f"Failed to query InfluxDB for measurement '{measurement.name}': {e}"
            ) from e
