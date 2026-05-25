"""Temperature notifier script.

Monitors indoor and outdoor temperatures via InfluxDB and sends notifications
when the outdoor temperature drops below the indoor temperature threshold.
"""

import argparse
import logging
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

from temperature_notifier.algorithm import compare_temperatures
from temperature_notifier.configuration import Configuration, ConfigurationError, load_configuration_from_file
from temperature_notifier.influxdb_service import InfluxDBService, InfluxDBServiceError
from temperature_notifier.notifiers import Notifier, NotifierError
from temperature_notifier.state_manager import StateManager, StateManagerError

try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version("temperature-notifier")
except PackageNotFoundError:
    import tomllib
    with open(Path(__file__).with_name("pyproject.toml"), "rb") as _f:
        __version__ = tomllib.load(_f)["project"]["version"]

logger = logging.getLogger(__name__)

SCRIPT_NAME = "temperature_notifier"
STATE_FILE = Path(__file__).parent / "notifier_state.json"
LOG_FILE_SIZE = 100 * 1024  # 100 KB
LOG_BACKUP_COUNT = 10  # Number of backup log files to keep


def configure_logging(log_name: str, debug: bool = False) -> None:
    """Configures logging to use a rotating file handler.

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


def main(args: Sequence[str] | None = None) -> int:
    """Main function.

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
    args = parser.parse_args(args)

    # Initialize logging
    configure_logging(SCRIPT_NAME, args.debug)

    # Load configuration
    try:
        config: Configuration = load_configuration_from_file(Path(__file__).parent / "config.yaml")
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
        notifiers: list[Notifier] = [cfg.create_notifier() for cfg in config.notifiers]

        # Perform the temperature comparison and send any resulting notification
        notification = compare_temperatures(
            config=config,
            influxdb_service=influxdb_service,
            state_manager=state_manager,
        )
        if notification is not None:
            for notifier in notifiers:
                notifier.send(notification)
    except (ConfigurationError, InfluxDBServiceError, NotifierError, StateManagerError) as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1
    finally:
        logger.info(f"{SCRIPT_NAME} script finished.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
