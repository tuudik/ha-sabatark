# Changelog

## [0.1.1]

- Access devices without stored options now default to impulse buttons, one per declared control. The old default
  for devices with fewer than two declared controls was a lock: that lock entity is no longer provided and shows as
  unavailable. To keep a lock, choose **Lock** for the device in the integration options. Otherwise remove the old
  entity under Settings → Devices & services → Entities: filter by the integration, select the lock marked as no
  longer provided and choose **Delete**.
- Add a door state binary sensor for access devices that report `open`; it is a garage door when the device is
  modelled as a cover.
- Garage covers send an impulse on open only when closed and on close only when open, and refuse both when the state
  is unknown. Toggle always sends an impulse.
- Name access buttons "Impulse", "Impulse 2" and so on. Unique ids do not change.
- Skip state-less security detectors that duplicate an access device's input.
- Add an Estonian translation.

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
