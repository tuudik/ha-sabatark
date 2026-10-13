# Releasing Sabatark

Home Assistant requires version 2026.10.0 or later. Release the Python library before the integration.

1. In `python-sabatark`, update the library version, run its checks, and tag that version to start
   its publishing workflow. Push the library tag according to that repository's release process.
2. Wait until the exact library version is published on PyPI. For version `X`,
   `https://pypi.org/pypi/sabatark/X/json` must return HTTP 200.
3. In `ha-sabatark`, set `custom_components/sabatark/manifest.json`'s requirement to `sabatark==X`
   and bump its integration `version`. Library and integration versions may differ.
4. Add release notes under `## [<integration version>]` in `CHANGELOG.md`. Run the integration tests,
   lint and formatting checks, and commit the release changes.
5. Create and push a tag `v<integration version>` on that commit. For example, integration version
   `0.1.0` uses tag `v0.1.0`.
6. The release workflow verifies that the tag matches the manifest and the pinned library is on PyPI.
   It runs the reusable validation workflow, including hassfest, HACS validation, pytest, lint,
   formatting and public-safety checks. A failed check prevents publication.
7. After validation, the workflow builds `sabatark.zip` and creates a GitHub Release with this
   version's changelog notes and the archive attached. HACS picks up the release for users who have
   added this repository as a custom integration repository.

The reusable validation workflow can install the sibling library repository before its first PyPI
release. The release workflow always requires the exact manifest pin to be available on PyPI first.
That fallback step is skipped as soon as the manifest's version exists on PyPI.

## Dependency updates

Dependabot checks GitHub Actions and the uv lockfile weekly. When it bumps
`pytest-homeassistant-custom-component`, keep `homeassistant` in `hacs.json` at or below the Home Assistant
version that release targets.

## Offline archive check

With the existing development environment, run:

```sh
uv run --offline python scripts/release.py build --output /tmp/sabatark.zip
```

The script verifies that `manifest.json` is at the zip root and that the archive is readable. It
includes the integration's Python modules, translations and brand images, and excludes `__pycache__`,
compiled Python files and `.DS_Store`. It does not contact PyPI when building an archive.

## Manual installation on Home Assistant OS

Download `sabatark.zip` from the GitHub Release. Using your configured file-access or terminal add-on,
create `/config/custom_components/sabatark` and unzip the archive into that directory. Its manifest
must end up at `/config/custom_components/sabatark/manifest.json`.

Restart Home Assistant. Add Sabatark through Settings → Devices & services, or keep your existing
Sabatark configuration when updating. Home Assistant installs the manifest's pinned library during
integration setup.
