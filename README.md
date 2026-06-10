# Temperature Notifier

The `temperature_notifier` module monitors indoor and outdoor temperatures using InfluxDB. It sends notifications via one or more configured notifier services (SimplePush, Home Assistant) if the outdoor temperature is lower than the indoor temperature and the indoor temperature exceeds a specified threshold.

## Features

- Monitors indoor and outdoor temperatures from an InfluxDB database.
- Sends notifications using one or more notifier services (SimplePush, Home Assistant).
- Configurable thresholds for temperature alerts, major temperature rises, and arming delta.
- Detects stale sensor data and sends a once-per-day warning notification when a sensor stops reporting.
- Logs activity with rotating log files.
- Maintains application state in a JSON file for persistent tracking.

## Requirements

The module requires the following Python dependencies, declared in [`pyproject.toml`](pyproject.toml):

- `influxdb`
- `pydantic`
- `pyyaml`
- `requests`
- `simplepush`

Install the dependencies using [uv](https://github.com/astral-sh/uv):
```sh
uv sync
```

## Configuration

Create a `config.yaml` file in the same directory as the script. Below is an example configuration:

```yaml
influxdb:
  host: "localhost"
  port: 8086
  database: "environment"
  max_data_age_minutes: 30        # Data older than this is considered stale
  measurements:
    indoor:
      name: "indoor"
      field: "temperature"
    outdoor:
      name: "outdoor"
      field: "temperature"

notifiers:
  - type: simplepush
    key: "YOUR_SIMPLEPUSH_KEY"
  # - type: home_assistant
  #   url: "http://localhost:8123"
  #   token: "YOUR_LONG_LIVED_ACCESS_TOKEN"
  #   service: "notify/mobile_app_your_phone"  # or "persistent_notification/create"

notification:
  min_indoor_temperature: 21.5    # Indoor temperature threshold in Celsius
  min_temperature_difference: 0.5 # Minimum indoor-outdoor delta (°C) when outdoor is warming or trend is unknown
  rapid_change_event:             # Rapid temperature change event settings
    rise: 3.0                     # Threshold for a significant temperature rise
    drop: 1.0                     # Threshold for a significant temperature drop
    window_minutes: 90            # Rolling window duration in minutes
    # min_peak_temperature: 25.0  # Optional: minimum outdoor peak (°C) required to fire the event.
                                  # Defaults to the current indoor temperature when omitted.
  reenable:                       # Re-enabling notifications settings
    cooldown_minutes: 180         # Cooldown period in minutes before re-enabling notifications
    min_rise_between_notifications: 2.0   # Minimum temperature rise (°C) required between notifications

arming:
  time: "08:00"                   # Time for arming [hh:mm]
```

### Notifier Selection

Multiple notifiers can be configured under the `notifiers` list — all configured notifiers receive every notification. Each notifier must have a `type` field:

| Type | Required fields | Notes |
|---|---|---|
| `simplepush` | `key` | Cloud push, works from anywhere |
| `home_assistant` | `url`, `token` | `service` defaults to `persistent_notification/create` |

For the `home_assistant` notifier, `service` is the HA service path as `domain/service`, e.g.:
- `notify/mobile_app_my_phone` — companion app push notification
- `persistent_notification/create` — visible in the HA dashboard sidebar

#### Finding the long-lived access token

1. Open Home Assistant and go to **Settings → Profile** (your user icon, bottom left).
2. Scroll to the bottom and click **Create Token** under **Long-Lived Access Tokens**.
3. Give it a name (e.g. `temperature-notifier`) and copy the token — it is only shown once.

#### Finding the phone service name

The service name depends on the device registered via the Home Assistant companion app. Query the HA REST API to list all available `notify` services:

```sh
curl -s \
  -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8123/api/services \
  | python3 -c "
import json, sys
for d in json.load(sys.stdin):
    if d['domain'] == 'notify':
        for name in d['services']:
            print('notify/' + name)
"
```

Look for a `notify/mobile_app_*` entry matching your phone. Use that value as the `service` field in `config.yaml`.

## Algorithm Details

### Temperature Comparison and Notification Logic

- **Daily Reset:** At the start of a new day, the notification flag, arming state, and stale warning flag are reset.
- **Temperature Fetch:** The latest indoor and outdoor temperatures are read from InfluxDB. Any data point older than `max_data_age_minutes` is treated as missing.
- **Stale Data Warning:** If one or both sensors have no recent data, a "Sensor Data Warning" notification is sent (at most once per day, and not before the configured `arming.time`). Temperature monitoring is skipped for that run.
- **Rolling Window Update:** The outdoor temperature is added to a rolling window of length `window_minutes` for trend analysis and rapid change detection.
- **Indoor Threshold Check:** If the indoor temperature is below `min_indoor_temperature`, no notification is sent.
- **Arming Logic:** The notifier arms itself once per day as soon as the current time reaches `arming.time`. Once armed the state persists for the rest of the day.
- **Rapid Change Event Detection:** Targets short-duration weather reversals — typically a fast-moving thunderstorm — that complete within the rolling window (`window_minutes`). If outdoor temperature rose by at least `rise` °C above the indoor temperature and subsequently dropped by at least `drop` °C within the window, the last notification timer is reset immediately so a new alert can fire without waiting for the cooldown. A fluctuation that never exceeded the indoor temperature is ignored because no meaningful "window opportunity was missed." The event is only acted upon once per rolling window.
- **Notification Cooldown and Re-enabling (slow weather cycles):** Handles cases where outdoor temperature reversed over a period longer than the rolling window (e.g. a slow-building afternoon storm): after the first notification the system waits until both guards are satisfied before sending another alert:
  - The cooldown period (`cooldown_minutes`) must have elapsed since the last notification.
  - Outdoor temperature must have risen by at least `min_rise_between_notifications` °C at some point since the last notification, confirming a meaningful warm period occurred.
  - On a typical monotonically cooling evening neither condition is met, so in practice one notification fires per evening unless the weather reverses.
- **First Notification:** Once armed, a trend check is applied to avoid spurious alerts when outdoor temperature is rising and only briefly dips below indoor (e.g. early morning). If outdoor is trending down, any outdoor < indoor qualifies. If outdoor is warming or the trend cannot yet be determined, a minimum delta of `min_temperature_difference` °C is required.
- **Re-notification:** See Rapid Change Event and Notification Cooldown above. The trend check is not applied — the upstream guards already confirm conditions are meaningful. A notification is sent whenever outdoor < indoor.


## Usage

Run the script using the following command:
```sh
uv run python main.py
```

Alternatively, you can use the provided shell script:

```sh
./temperature_notifier.sh
```

## Logging

Logs are stored in a file named `temperature_notifier.log` in the same directory as the script. Logs are rotated by size, and up to 10 backup log files are retained.

## Deployment

To run the script periodically, you can use a cron job. For example, to execute the script every 10 minutes:

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
- SimplePush for push notification services.
- Home Assistant for home automation and mobile notifications.
