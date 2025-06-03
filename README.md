# Temperature Notifier

The `temperature_notifier` module monitors indoor and outdoor temperatures using InfluxDB. It sends notifications via the SimplePush service if the outdoor temperature is lower than the indoor temperature and the indoor temperature exceeds a specified threshold.

## Features

- Monitors indoor and outdoor temperatures from an InfluxDB database.
- Sends notifications using one or more notifier services (SimplePush, email, etc.).
- Configurable thresholds for temperature alerts, major temperature rises, and arming delta.
- Logs activity with rotating log files.
- Maintains application state in a JSON file for persistent tracking.

## Requirements

The module requires the following Python dependencies, which are listed in the [`requirements.txt`](requirements.txt) file:

- `influxdb`
- `jsonschema`
- `pyyaml`
- `simplepush`
- (add any additional notifier dependencies, e.g., `smtplib` for email)

Install the dependencies using:
```sh
pip install -r requirements.txt
```

## Configuration

Create a `config.yaml` file in the same directory as the script. Below is an example configuration:

```yaml
influxdb:
  host: "localhost"
  port: 8086
  database: "environmentMonitoring"
  measurements:
    indoor:
      name: "LivingRoom"
      field: "tCels"
    outdoor:
      name: "outdoor"
      field: "temperature"

notifiers:
  - type: simplepush
    key: "YOUR_SIMPLEPUSH_KEY"

notification:
  min_indoor_temperature: 21.5    # Indoor temperature threshold in Celsius
  rapid_change_event:             # Rapid temperature change event settings
    rise: 3.0                     # Threshold for a significant temperature rise
    drop: 1.0                     # Threshold for a significant temperature drop
    window_minutes: 90            # Rolling window duration in minutes
  reenable:                       # Re-enabling notifications settings
    cooldown_minutes: 180         # Cooldown period in minutes before re-enabling notifications
    min_rise_between_notifications: 2.0   # Minimum temperature rise (°C) required between notifications

arming:
  temperature_delta: 2.0          # Temperature delta for arming in Celsius
  time: "08:00"                   # Time for arming [hh:mm]
```

### Notifier Selection

- Multiple notifiers can be configured under the `notifiers` list.
- Each notifier must have a `type` field (e.g., `simplepush`, `email`).
- Each notifier type has its own configuration fields.

## Algorithm Details

### Temperature Comparison and Notification Logic

- **Daily Reset:** At the start of a new day, the notification flag and arming state are reset.
- **Temperature Fetch:** The latest indoor and outdoor temperatures are read from InfluxDB.
- **Rolling Window Update:** The outdoor temperature is added to a rolling window of length `window_minutes` for trend analysis and rapid change detection.
- **Indoor Threshold Check:** If the indoor temperature is below `min_indoor_temperature`, no notification is sent.
- **Arming Logic:** The notifier "arms" itself only if the outdoor temperature is at least `temperature_delta` °C higher than the indoor temperature or after the configured arming time.
- **Rapid Change Event Detection:** If a significant temperature rise (`rise`) followed by a significant drop (`drop`) is detected within the rolling window, a notification can be sent (unless already notified for this event within the window).
- **Notification Cooldown and Re-enabling:**
  - After a notification, a cooldown period (`cooldown_minutes`) must pass before another notification can be sent.
  - Additionally, there must be a minimum temperature rise (`min_rise_between_notifications`) since the last notification before a new notification is allowed.
- **Notification Condition:** If the notifier is armed and the outdoor temperature drops below the indoor temperature, a notification is sent via all configured notifiers.

**Note:**  
- The configuration and logic are designed to avoid spamming notifications and to only alert when meaningful temperature changes occur.
- The `rapid_change_event` group is for detecting sudden weather changes (e.g., rain cooldowns).
- The `reenable` group ensures notifications are not sent repeatedly unless there has been a significant warm-up and the cooldown period has passed.


## Usage

Run the script using the following command:
```sh
python main.py
```

Alternatively, you can use the provided shell script to run the notifier (setup virtual environment required):

```sh
./temperature_notifier.sh
```

## Logging

Logs are stored in a file named `temperature_notifier.log` in the same directory as the script. Logs are rotated by size, and up to 10 backup log files are retained.

## Deployment

To run the script periodically, you can use a cron job. For example, to execute the script every hour:

1. Open the crontab editor:
   ```sh
   crontab -e
   ```

2. Add the following entry:
   ```sh
   */10 * * * * /path/to/temperature_notifier.sh > /path/to/temperature_notifier_cron.log 2>&1
   ```

## License

This project is licensed under the MIT License. See the [`LICENSE`](LICENSE) file for details.

## Acknowledgments

- InfluxDB for time-series data storage.
- SimplePush for notification services.