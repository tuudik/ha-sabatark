# Changelog

## [0.1.0]

- Configure a controller account and select one site per Home Assistant entry.
- Remember sessions across restarts and request reauthentication when needed.
- Add lights, relay switches, binary sensors and numeric sensors with local push updates.
- Follow the on/off, brightness and open-button controls each device declares; dimmers support brightness.
- Mark every entity unavailable while the controller is unreachable.
- Expose wall-switch presses, long presses and double presses as button events.
- Model access devices as locks, garage covers or output pulse buttons through integration options.
- Provide redacted diagnostics and original integration icons.
- Package `sabatark.zip` for HACS and manual installation on Home Assistant OS.
- Require Home Assistant 2026.10.0 or later (Python 3.14).

Alarm panels, blinds, ventilation and sauna controls are not included.
