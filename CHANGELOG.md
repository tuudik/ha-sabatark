# Changelog

## [0.2.1] - 2026-10-14

### Fixed
- Devices the integration no longer provides, such as the security detectors skipped since 0.1.1 as duplicates of an
  access device's input, are removed from the device registry when the integration starts.
- Such devices can also be deleted from their device page. The site hub and devices still provided by the controller
  cannot be deleted while the entry is set up.

## [0.2.0] - 2026-10-14

### Added
- Restore outputs after a power cut. Choose lights and switches under **Restore after power loss** in the
  integration options. When the I/O module that drives a selected output comes back after losing power, the output
  is switched back to its last state before the outage, including the brightness of dimmers. Outputs the controller
  has already set again are left alone. Access devices cannot be selected.
- Fire the `sabatark_outputs_restored` event and show a notification listing the restored outputs.
- Add a diagnostic **Last power loss** sensor to the site hub device and include the restore state in diagnostics.

### Changed
- The integration options open with a menu: configure an access device, or restore after power loss.

## [0.1.2] - 2026-10-14

### Added
- Sabatark logo and icon, with dark-theme variants, shown in Home Assistant and in the README.

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
