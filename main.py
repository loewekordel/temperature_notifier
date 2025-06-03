"""
This script monitors indoor and outdoor temperatures using InfluxDB.
It sends notifications if the outdoor temperature is lower than the indoor temperature
and the indoor temperature exceeds a specified threshold.
It uses the SimplePush service for notifications.
"""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from typing import Sequence

from temperature_notifier.algorithm import compare_temperatures
from temperature_notifier.configuration import Configuration
from temperature_notifier.configuration import ConfigurationError
from temperature_notifier.configuration import load_configuration_from_file
from temperature_notifier.configuration import SimplePushConfiguration
from temperature_notifier.influxdb_service import InfluxDBService
from temperature_notifier.influxdb_service import InfluxDBServiceError
from temperature_notifier.notifiers import SimplePushNotifier
from temperature_notifier.state_manager import StateManager
from temperature_notifier.state_manager import StateManagerError
from temperature_notifier.notifiers import Notifier
from temperature_notifier.notifiers import NotifierError

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

SCRIPT_NAME = "temperature_notifier"
STATE_FILE = Path("notifier_state.json")
LOG_FILE_SIZE = 100 * 1024  # 2 KB
LOG_BACKUP_COUNT = 10  # Number of backup log files to keep
NOTIFIER_CONFIG_TO_CLASS = {
    SimplePushConfiguration: SimplePushNotifier,
}


def configure_logging(log_name: str, debug: bool = False) -> None:
    """
    Configures logging to use a rotating file handler.

    :param log_name: The name of the log file.
    """
    log_file = Path(__file__).with_name(f"{log_name}.log")

    # Create a RotatingFileHandler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_FILE_SIZE,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s|%(levelname)-7s| %(message)s")
    )

    # Create a StreamHandler for console logging
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(levelname)-7s| %(message)s")
    )  # No asctime for console

    # Configure the root logger
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=[
            file_handler,  # File handler for detailed logs
            console_handler,  # Console handler for real-time logs
        ],
    )


def main(args: Optional[Sequence[str]] = None) -> int:
    """
    Main function.

    :return: Exit code, 0 for success, 1 for failure.
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Temperature Notifier Script",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the version and exit.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    # Initialize logging
    configure_logging(SCRIPT_NAME, args.debug)

    # Load configuration
    try:
        config: Configuration = load_configuration_from_file("config.yaml")
    except ConfigurationError as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1

    logger.info(f"{SCRIPT_NAME} script started.")
    try:
        # Initialize the InfluxDB service
        influxdb_service = InfluxDBService(
            host=config.influxdb.host,
            port=config.influxdb.port,
        )
        influxdb_service.switch_database(config.influxdb.database)

        # Initialize the StateManager
        state_manager = StateManager(
            STATE_FILE,
            rolling_window_minutes=config.notification.rapid_change_event.window_minutes,
        )

        # Initialize the Notifier
        notifiers: list[Notifier] = []
        for notifier_cfg in config.notifiers:
            notifier_class = NOTIFIER_CONFIG_TO_CLASS.get(type(notifier_cfg))
            if not notifier_class:
                logger.error(
                    f"No notifier class registered for config type '{type(notifier_cfg).__name__}'"
                )
                continue
            notifiers.append(notifier_class(**notifier_cfg.__dict__))

        # Perform the temperature comparison
        compare_temperatures(
            config=config,
            influxdb_service=influxdb_service,
            state_manager=state_manager,
            notifiers=notifiers,
        )
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except InfluxDBServiceError as e:
        logger.error(f"InfluxDB error: {e}")
        return 1
    except NotifierError as e:
        logger.error(f"Notifier error: {e}")
        return 1
    except StateManagerError as e:
        logger.error(f"State manager error: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1
    finally:
        logger.info(f"{SCRIPT_NAME} script finished.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
