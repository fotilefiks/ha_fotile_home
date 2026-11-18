# Fotile - Home Assistant Integration

Official Home Assistant integration for Fotile smart kitchen appliances. Brings
Fotile range hoods, stoves and more into Home Assistant for unified control and
automation.

> English | [中文](README.zh-CN.md)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fotilefiks&repository=ha_fotile_home&category=integration)

---

## Supported Devices

| Device | HA Entity | Features |
|--------|-----------|----------|
| Range hood | Fan / Light | Master power switch, 3 fan speeds (low / auto / high), light switch |
| Stove | Binary Sensor ×2 | Left / right burner on-state (**read-only**) |
| Dishwasher `JBCD7E-02-V6A` | Switch / Select / Button / Sensor | Power, five wash modes, start/resume, pause, cancel and status monitoring |

> **About stoves**: the stove fields Fotile exposes to the cloud-cloud protocol
> (`LeftStoveState` / `RightStoveState`) have read (`R`) permission only, so this
> integration reports their state but **does not control the stove**.
>
> Additional categories (water heater, water purifier, sterilizer, etc.) will be
> added as their cloud models become available.

### How device types are identified

**The `devType` field is not used** -- Fotile's cloud-cloud spec provides no
`devType` lookup table. Device category is decided by the `services[].sid`
capability declarations returned by `DeviceDiscovery`; see
`const.DEVICE_KIND_BY_SID`:

| Category | Matches any of these sids |
|----------|---------------------------|
| Range hood | `PowerSwitch` / `FanLevel` / `Light` |
| Stove | `LeftStoveState` / `RightStoveState` |
| Dishwasher | `JBCD*` model name or dishwasher-specific shadow fields |

One device may match multiple categories (e.g. an integrated cooker-hood), in
which case all matching platform entities are created. Each entity also
double-checks that the device actually declares the corresponding sid, avoiding
always-unavailable light entities for hoods without a light.

### Dishwasher V6A cloud fallback

The HA facade currently returns an empty device list for the dishwasher
`JBCD7E-02-V6A`, even though the appliance is visible in the Fotile account.
The integration therefore keeps the facade as the primary path and falls back to
the 方太幸福家 App API only when the facade returns no devices.

The fallback deliberately reuses the existing OAuth authorization:

1. `GET /v3/all/homes/devices` discovers appliances omitted by the facade.
2. `POST /v2/device/batchQueryShadow` reads their complete property shadow.
3. `POST /iot-mqttManager/routeService` returns the App MQTT endpoint.
4. Control commands are sent to `control/{productId}/{deviceId}`.

Status entities are created from the fields actually returned by the device,
so unknown future fields remain visible for diagnostics. The V6A implementation
provides:

- Online, power, work state, selected programme, remaining time, door lock,
  error code, detergent/salt level and other cloud attributes.
- Power switch.
- Smart, intensive, standard, eco and quick wash mode selection.
- Start/resume, pause and cancel controls.
- A separate `*_HA` MQTT client id, avoiding takeover of the phone App session.

The power command and status path have been tested on a real V6A. Wash-mode
mapping follows the existing 1025-series dishwasher implementation; starting an
actual wash should still be treated as an appliance operation and used with
care.

> The App API has no public stability or compatibility contract. If Fotile
> changes these endpoints, the facade-backed devices will continue to work and
> only the fallback path will be affected.

---

## Installation

### Method 1: HACS (recommended)

1. Home Assistant → HACS → Integrations
2. Search for **Fotile**
3. Click **Install**
4. Restart Home Assistant

### Method 2: Manual

1. Download this repository
2. Copy the `custom_components/fotile` folder into your Home Assistant
   `custom_components` directory
3. Restart Home Assistant

---

## Configuration

1. Home Assistant → Settings → Devices & Services → Add Integration
2. Search for **Fotile**
3. Your browser redirects to the **Fotile website** -- log in with your phone
   number and SMS code, then authorize
4. You are returned to Home Assistant, which auto-discovers and adds all Fotile
   devices bound to your account

> **Security**: this integration uses OAuth 2.0 Authorization Code + PKCE. Login
> and SMS-code entry happen entirely on Fotile's own page. **Home Assistant never
> sees or stores your phone number, password, or SMS code** -- it only holds an
> access token that you can revoke at any time on Fotile's side.

### Application credentials

The official Fotile release has credentials built in -- no action needed.

If you run a self-deployed development build, add your own Client ID under
**Settings → Devices & Services → ⋮ (top-right menu) → Application credentials**:

| Field | Value |
|-------|-------|
| Client type | Public client / native app |
| Auth mode | authorization_code + PKCE (S256) |
| Redirect URI | `https://my.home-assistant.io/redirect/oauth` |

> The redirect URI must match **exactly character-by-character**. OAuth 2.1
> requires exact string matching; prefix or partial matches are rejected.

### Options

After installation, go to **Devices & Services → Fotile → Configure**:

| Option | Description | Default |
|--------|-------------|---------|
| Update interval | Device status refresh interval (seconds) | 30 (range 10–300) |
| Devices | Only expose the selected devices; leave all unchecked to include every device | All devices |

---

## Requirements

- Home Assistant Core ≥ 2024.11.0
- A Fotile account with devices bound
- Devices connected via WiFi and online in the Fotile app
- Internet access (this integration uses cloud polling)

> The integration relies on a re-auth helper introduced in Home Assistant 2024.11;
> it will not work on older versions.

---

## Cloud Protocol

This integration normally talks only to the Home Assistant facade (`/ha/v1`)
provided by Fotile. CorpId, the cloud-cloud envelope (`header` / `namespace`) and
the enterprise-side protocol are owned by the server. For appliance families
that the facade does not yet return, such as V6A, the App API fallback uses the
same OAuth access token with Fotile App request headers.

### Flat REST

Every endpoint is plain flat REST, authenticated with
`Authorization: Bearer <access_token>`:

```
POST https://api.fotile.com/open-cloud/ha/v1/devices
Authorization: Bearer <access_token>
Content-Type: application/json

{ }
```

| Endpoint | Purpose | Used in |
|----------|---------|---------|
| `POST /accept-grant` | Account authorization (**required first**) | `config_flow.py`, `__init__.py` |
| `POST /devices` | Device list | `coordinator.py` |
| `POST /devices/{id}/snapshot` | Device status | `coordinator.py` |
| `POST /devices/{id}/command` | Device control (write property) | entity platforms |
| `POST /devices/{id}/subscribe` | Device subscription | debug only |

### AcceptGrant is a prerequisite

The facade checks, for every endpoint except `/accept-grant`, that the user has
granted access to Home Assistant; without it the server returns **HTTP 401**.

The integration calls it in two places:
1. `config_flow.py` -- right after authorization, using the returned
   `thirdPartyUserId` as the `unique_id` (prevents duplicate entries for the same
   account) and persisting it.
2. `__init__.py` -- on integration load (reusing the persisted value when present
   to avoid duplicate requests).

The endpoint is idempotent (the server updates an existing relationship), so
repeated calls are safe.

### Control is "write property", not a verb command

```json
{
  "sid": "FanLevel",
  "data": { "FanLevel": 3 },
  "prodId": "000b"
}
```

There is no command verb name -- only `sid` (service identifier) + `data`
(property key/value). `prodId` is optional and improves server-side matching.

### Errors are mapped onto HTTP status codes

The facade maps error classes onto HTTP statuses and keeps the body flat
(`{"code": ..., "description": ...}`):

| HTTP | Meaning | Client behaviour |
|------|---------|------------------|
| 200 | Success | Parsed normally |
| 401 / 403 | Invalid token or user not granted | Trigger HA re-auth |
| 4xx | Business error (`10009` not found / `10010` unsupported / `10011` offline) | Raise `FotileBusinessError`, token state untouched |
| 5xx | Server failure | Raise `FotileConnectionError`, retried with backoff |

### Status data is two-level nested

```json
{ "devices": [{ "thirdPartyDevId": "...", "status": "online",
    "services": [{ "ts": "...", "sid": "PowerSwitch", "data": { "PowerSwitch": 1 } }] }] }
```

`flatten_service_data()` in `core/mapping.py` flattens this to
`{"PowerSwitch.PowerSwitch": 1}`, using `sid` as a prefix to prevent same-named
attributes across services from overwriting each other. `const.STATUS_FIELD_MAP`
then maps these to internal field names consumed by entities.

### Online status comes only from the snapshot

`DeviceDiscovery` (the device list) **does not provide online status**; `online`
is backfilled from the `DeviceSnapshot` `status` field (`online`/`offline`).

Accordingly, the coordinator must send one snapshot request per device per cycle
(the spec requires `thirdPartyDevIds` to carry a single id); requests are made
concurrently with `asyncio.gather`. The device list has a 5-minute cache and is
not re-fetched every cycle.

### Why event push is not implemented

Spec section 2.4 defines Fotile actively pushing device events
(`DeviceStatusChanged`, etc.) to third parties, but requires the third party to
provide a **publicly reachable callback URL**. Home Assistant is typically
deployed locally with no public ingress, so it cannot receive pushes; polling is
used instead (`"iot_class": "cloud_polling"` in `manifest.json`).

---

## Issues

Please file GitHub issues and include:
1. Home Assistant version
2. Device model
3. Logs (enable debug logging in `configuration.yaml`):

```yaml
logger:
  default: info
  logs:
    custom_components.fotile: debug
```

> Troubleshooting tip: first check that `const.HA_API_BASE_URL` is reachable and
> `client_id` is correct, then enable debug logging for
> `custom_components.fotile` to locate whether the issue is in auth, the device
> list, or status parsing.

---

## License

Apache License 2.0
