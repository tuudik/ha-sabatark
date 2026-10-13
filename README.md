# ha-sabatark

Home Assistant custom integration for Agatark (EnLife) home automation controllers. It talks to the controller's
local HTTP API through the [`sabatark`](https://github.com/tuudik/python-sabatark) library and receives changes
from the controller's event stream (local push, no polling).

Unofficial; not affiliated with the controller vendor. Work in progress.

## Setup

1. Copy `custom_components/sabatark` into your Home Assistant `config/custom_components` directory and restart.
2. Settings → Devices & services → Add integration → **Sabatark (Agatark)**.
3. Enter the controller URL (for example `http://192.0.2.10`), the e-mail and password of a controller account,
   then pick the site. Add the integration again for other sites.

The password is not stored. The integration keeps the derived login token and a remembered session, so restarts do
not log in again. When the controller rejects the login, Home Assistant asks for the password again.

## Entities

Each controller device becomes a Home Assistant device in its room, attached to a hub device for the site.
Hardware modules and bus drivers get no entities.

| Controller device | Entity |
|---|---|
| Light outputs (`light`, `outputPwm`, or outputs with light usage) | `light` (on/off, brightness for dimmers) |
| Other outputs | `switch` |
| Motion detectors | `binary_sensor` (motion) |
| Door and window contacts | `binary_sensor` (door, window or opening) |
| Fire, smoke, CO and other 24-hour detectors | `binary_sensor` (smoke, CO, gas, moisture or safety) |
| Generic inputs | `binary_sensor` |
| Wall switches | `binary_sensor` with the raw input, disabled by default |
| Temperature, humidity, CO2, illuminance, voltage, current | `sensor` |
| Other numeric status values | `sensor`, disabled by default |

On/off and brightness controls follow the controls each device declares in the controller's user interface.
Access devices with two or more declared open buttons default to pulse buttons, others to a lock; integration options
override the default.

A device that reports itself offline, or a lost connection to the controller, makes its entities unavailable.

## Limitations

- Blinds, ventilation and the sauna are not supported yet.

## Development

```sh
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

The development environment expects the library checked out next to this repository (`../python-sabatark`).

## License

MIT
