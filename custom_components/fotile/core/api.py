"""Fotile API client (flat REST against the HA facade)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiohttp

from ..const import (
    APP_API_BASE_URL,
    APP_API_HEADERS,
    APP_DEVICES_PATH,
    APP_ROUTE_PATH,
    APP_SHADOW_PATH,
    CODE_DEVICE_OFFLINE,
    FAN_LEVEL_HIGH,
    FAN_LEVEL_STANDBY,
    HA_API_BASE_URL,
    KEY_DATA,
    KEY_DESCRIPTION,
    KEY_DEVICES,
    KEY_SERVICE_ID,
    RESPONSE_KEY_CODE,
    SID_FAN_LEVEL,
    SID_LIGHT,
    SID_POWER_SWITCH,
    SWITCH_OFF_VALUE,
    SWITCH_ON_VALUE,
)
from .authbase import (
    AbstractAuth,
    FotileApiError,
    FotileAuthError,
    NoAuth,
    StaticTokenAuth,
)
from .mapping import (
    find_snapshot_device,
    map_app_device_fields,
    map_app_shadow,
    map_device_fields,
    map_status_fields,
    to_bool,
)
from .mqtt import FotileMqtt

_LOGGER = logging.getLogger(__name__)

# Re-exported so callers keep importing from this module.
__all__ = [
    "AbstractAuth",
    "FotileApiError",
    "FotileAuthError",
    "FotileBusinessError",
    "FotileClient",
    "FotileConnectionError",
    "NoAuth",
    "StaticTokenAuth",
    "is_ha_config_entry_exception",
]


class FotileConnectionError(FotileApiError):
    """Network connection error."""


class FotileBusinessError(FotileApiError):
    """Business error returned by the facade (HTTP 4xx)."""

    def __init__(self, code: int | None, description: str) -> None:
        self.code = code
        self.description = description
        super().__init__(200, f"Fotile business error code={code}: {description}")


def is_ha_config_entry_exception(err: BaseException) -> bool:
    """True for HA config-entry lifecycle exceptions (must propagate)."""
    try:
        from homeassistant.exceptions import (  # noqa: PLC0415
            ConfigEntryAuthFailed,
            ConfigEntryNotReady,
        )
    except ImportError:  # pragma: no cover
        return False

    return isinstance(err, (ConfigEntryAuthFailed, ConfigEntryNotReady))


class FotileClient:
    """Thin client for the Fotile HA facade.

    Only flat REST is spoken here: CorpId, the cloud-cloud envelope and the
    enterprise-side protocol are owned by the server.
    """

    def __init__(
        self,
        auth: AbstractAuth,
        session: aiohttp.ClientSession | None = None,
        base_url: str = HA_API_BASE_URL,
    ) -> None:
        self._auth = auth
        self._session = session or aiohttp.ClientSession()
        # Only close a session we created; HA's shared session is managed by HA.
        self._owns_session = session is None
        self._base_url = base_url.rstrip("/")
        # thirdPartyUserId from AcceptGrant; used as the HA unique_id only.
        self._third_party_user_id: str | None = None
        # Devices discovered through the 方太幸福家 App API when the HA facade
        # omits their appliance family.
        self._app_devices: dict[str, dict[str, Any]] = {}

    @property
    def auth(self) -> AbstractAuth:
        return self._auth

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    @property
    def third_party_user_id(self) -> str | None:
        return self._third_party_user_id

    def set_third_party_user_id(self, value: str | None) -> None:
        self._third_party_user_id = value

    @property
    def app_device_count(self) -> int:
        """Number of devices discovered through the App API fallback."""
        return len(self._app_devices)

    # ---- unified request ----

    @staticmethod
    def _parse_error(text: str) -> tuple[int | None, str]:
        """Best-effort parse of code/description from an error body."""
        try:
            body = json.loads(text)
        except (TypeError, ValueError):
            return None, ""
        if not isinstance(body, dict):
            return None, ""
        code = body.get(RESPONSE_KEY_CODE)
        description = body.get(KEY_DESCRIPTION) or ""
        return (code if isinstance(code, int) else None), str(description)

    async def _call_proxy(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST to the facade and return the flat response body."""
        url = f"{self._base_url}{path}"

        try:
            response = await self._auth.async_request(
                self._session,
                "POST",
                url,
                json=payload if payload is not None else {},
                headers={"Content-Type": "application/json"},
            )

            if response.status in (401, 403):
                text = await response.text()
                raise FotileAuthError(response.status, f"Unauthorized: {text[:200]}")

            if response.status >= 400:
                text = await response.text()
                code, description = self._parse_error(text)
                _LOGGER.warning(
                    "Facade %s failed status=%s code=%s description=%s",
                    path,
                    response.status,
                    code,
                    description,
                )
                raise FotileBusinessError(code, description or text[:500])

            # Skip aiohttp's Content-Type check: the server may return
            # non-JSON content types with valid JSON bodies, and a wrong type
            # must surface as an API error, not a silent retry loop.
            raw = await response.json(content_type=None)

        except aiohttp.ClientError as err:
            # HA's OAuth2 token errors subclass aiohttp.ClientError for
            # backwards compatibility; they must propagate unchanged.
            if is_ha_config_entry_exception(err):
                raise
            raise FotileConnectionError(0, f"Connection error: {err}") from err

        if not isinstance(raw, dict):
            raise FotileApiError(
                200, f"Response is not a JSON object: {type(raw).__name__}"
            )
        return raw

    async def _call_app_api(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Call the 方太幸福家 App API with the same OAuth access token."""
        if not self._third_party_user_id:
            raise FotileAuthError(
                401,
                "Cannot use App API without thirdPartyUserId from AcceptGrant",
            )

        token = await self._auth.async_get_access_token()
        headers = {
            **APP_API_HEADERS,
            "Access-Token": token,
            "X-User": self._third_party_user_id,
        }
        url = f"{APP_API_BASE_URL}{path}"

        try:
            async with self._session.request(
                method,
                url,
                json=payload,
                headers=headers,
            ) as response:
                text = await response.text()
                if response.status in (401, 403):
                    raise FotileAuthError(
                        response.status,
                        f"App API unauthorized: {text[:300]}",
                    )
                if response.status >= 400:
                    code, description = self._parse_error(text)
                    raise FotileBusinessError(
                        code,
                        description or text[:500],
                    )
                try:
                    return json.loads(text) if text else None
                except ValueError as err:
                    raise FotileApiError(
                        response.status,
                        f"App API returned invalid JSON: {text[:300]}",
                    ) from err
        except aiohttp.ClientError as err:
            raise FotileConnectionError(
                0,
                f"App API connection error: {err}",
            ) from err

    # ---- AcceptGrant ----

    async def accept_grant(self) -> str | None:
        """Establish the account grant; required before every other endpoint."""
        resp = await self._call_proxy("/accept-grant")

        user_id = resp.get("thirdPartyUserId")
        if user_id is not None:
            user_id = str(user_id)
        self._third_party_user_id = user_id

        if user_id is None:
            _LOGGER.warning("AcceptGrant response missing thirdPartyUserId")
        else:
            _LOGGER.info("AcceptGrant succeeded, thirdPartyUserId = %s", user_id)

        return user_id

    # ---- devices ----

    async def get_devices(self) -> list[dict[str, Any]]:
        """List all bound devices.

        The device list carries no online status; ``online`` is backfilled by
        :meth:`get_device_status`. Pagination is aggregated by the facade.
        """
        resp = await self._call_proxy("/devices")

        devices: list[dict[str, Any]] = []
        for raw in resp.get(KEY_DEVICES) or []:
            mapped = map_device_fields(raw)
            device_id = mapped.get("device_id")
            if not device_id:
                _LOGGER.warning("Skipping device without thirdPartyDevId: %s", raw)
                continue
            devices.append(
                {
                    "device_id": str(device_id),
                    "name": mapped.get("name") or str(device_id),
                    "device_type": mapped.get("device_type") or "",
                    "model": mapped.get("model") or "",
                    "manufacturer": mapped.get("manufacturer") or "",
                    "product_id": mapped.get("product_id") or "",
                    "serial_number": mapped.get("serial_number") or "",
                    "service_ids": mapped.get("service_ids") or [],
                    "service_types": mapped.get("service_types") or [],
                    "online": False,  # backfilled by snapshot
                    "_raw": mapped.get("_raw"),
                }
            )

        if devices:
            return devices

        _LOGGER.info(
            "Fotile HA facade returned no devices; trying the App API fallback"
        )
        raw_app = await self._call_app_api("GET", APP_DEVICES_PATH)
        app_devices = raw_app.get("deviceList") if isinstance(raw_app, dict) else None
        if not isinstance(app_devices, list):
            _LOGGER.warning(
                "Fotile App API returned an unexpected device list: %s",
                raw_app,
            )
            return []

        for raw in app_devices:
            mapped = map_app_device_fields(raw)
            if mapped is None:
                continue
            devices.append(mapped)
            self._app_devices[mapped["device_id"]] = mapped

        _LOGGER.info(
            "Fotile App API fallback discovered %d device(s)",
            len(self._app_devices),
        )
        return devices

    # ---- device status ----

    async def get_device_status(self, device_id: str) -> dict[str, Any]:
        """Snapshot for one device.

        Returns mapped internal fields plus online, _flat, _fetched_at.
        """
        app_device = self._app_devices.get(str(device_id))
        if app_device is not None:
            return await self._get_app_device_status(app_device)

        resp = await self._call_proxy(f"/devices/{device_id}/snapshot")

        target = find_snapshot_device(resp, device_id)
        if target is None:
            _LOGGER.warning(
                "Device %s not found in snapshot (response had %d device(s))",
                device_id,
                len(resp.get(KEY_DEVICES) or []),
            )
            return {"online": False, "_flat": {}, "_fetched_at": time.time()}

        status = map_status_fields(target)
        status["_fetched_at"] = time.time()
        return status

    async def _get_app_device_status(
        self,
        device: dict[str, Any],
    ) -> dict[str, Any]:
        """Read a V6A/high-appliance snapshot through batchQueryShadow."""
        payload = {
            "devices": [
                {
                    "productId": device["product_id"],
                    "deviceId": int(device["device_id"]),
                }
            ]
        }
        resp = await self._call_app_api("POST", APP_SHADOW_PATH, payload)
        shadows = (
            (resp.get("data") or {}).get("deviceShadows")
            if isinstance(resp, dict)
            else None
        )
        if not isinstance(shadows, list) or not shadows:
            _LOGGER.warning(
                "Fotile App API returned no shadow for device %s: %s",
                device["device_id"],
                resp,
            )
            return {
                "online": False,
                "_flat": {},
                "_fetched_at": time.time(),
            }

        status = map_app_shadow(shadows[0])
        status["_fetched_at"] = time.time()
        return status

    async def _get_app_broker(self) -> dict[str, Any]:
        """Fetch the current App MQTT broker and client id."""
        if not self._third_party_user_id:
            raise FotileAuthError(401, "Missing Fotile App user id")
        response = await self._call_app_api(
            "POST",
            APP_ROUTE_PATH,
            {
                "bussinessType": 1,
                "userId": self._third_party_user_id,
                "requestType": 1,
                "clientType": 1,
            },
        )
        if not isinstance(response, list) or not response:
            raise FotileConnectionError(0, f"Invalid MQTT route response: {response}")
        broker = response[0]
        if not isinstance(broker, dict) or not broker.get("ip"):
            raise FotileConnectionError(0, f"Invalid MQTT broker: {broker}")
        return broker

    async def send_app_command(
        self,
        device_id: str,
        command: dict[str, Any],
    ) -> None:
        """Publish one command through the App MQTT cloud channel."""
        device = self._app_devices.get(str(device_id))
        if device is None:
            raise FotileApiError(404, f"Unknown App device: {device_id}")
        if not self._third_party_user_id:
            raise FotileAuthError(401, "Missing Fotile App user id")

        broker = await self._get_app_broker()
        token = await self._auth.async_get_access_token()
        client = FotileMqtt(
            f"{broker.get('clientId') or 'Fotile_APP'}_HA",
            self._third_party_user_id,
            token,
        )
        topic = f"control/{device['product_id']}/{device['device_id']}"
        try:
            await client.connect(
                str(broker["ip"]),
                int(broker.get("port", 1883)),
                int(broker.get("keepalived", 30)),
            )
            await client.publish(topic, command)
        except (ConnectionError, OSError, TimeoutError) as err:
            raise FotileConnectionError(
                0,
                f"Fotile MQTT command failed: {err}",
            ) from err
        finally:
            await client.disconnect()

        _LOGGER.info(
            "Sent Fotile App command for %s: %s",
            device_id,
            sorted(command),
        )

    async def set_dishwasher_power(self, device_id: str, on: bool) -> None:
        await self.send_app_command(
            device_id,
            {"PowerSwitchAll": 1 if on else 0},
        )

    async def start_dishwasher(self, device_id: str, mode: int) -> None:
        await self.send_app_command(
            device_id,
            {
                "PowerSwitchAll": 1,
                "WorkMode": mode,
                "WorkState": 1,
            },
        )

    async def resume_dishwasher(self, device_id: str) -> None:
        await self.send_app_command(device_id, {"WorkState": 1})

    async def pause_dishwasher(self, device_id: str) -> None:
        await self.send_app_command(device_id, {"WorkState": 2})

    async def stop_dishwasher(self, device_id: str) -> None:
        await self.send_app_command(device_id, {"WorkState": 0})

    # ---- device subscription ----

    async def subscribe_device(self, device_id: str) -> dict[str, Any]:
        """Subscribe to a device.

        Subscriptions only affect event push. HA runs locally with no public
        callback, so this integration polls (``iot_class: cloud_polling``) and
        subscribing is not required. Kept to verify whether the snapshot
        endpoint demands a subscription first.
        """
        return await self._call_proxy(f"/devices/{device_id}/subscribe")

    # ---- device command ----

    async def send_command(
        self,
        device_id: str,
        sid: str,
        data: dict[str, Any],
        prod_id: str | None = None,
    ) -> dict[str, Any]:
        """Write a property: request body is ``sid`` + ``data``."""
        body: dict[str, Any] = {
            KEY_SERVICE_ID: sid,
            KEY_DATA: data,
        }
        if prod_id:
            body["prodId"] = prod_id

        return await self._call_proxy(f"/devices/{device_id}/command", body)

    # ---- online check ----

    async def is_device_online(self, device_id: str) -> bool:
        try:
            status = await self.get_device_status(device_id)
        except FotileBusinessError as err:
            if err.code == CODE_DEVICE_OFFLINE:
                return False
            raise
        return to_bool(status.get("online"), default=False)

    # ---- category convenience methods (confirmed thing model, 2026-10) ----

    async def set_property(
        self,
        device_id: str,
        sid: str,
        attr: str,
        value: Any,
        prod_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.send_command(device_id, sid, {attr: value}, prod_id)

    async def turn_on(
        self, device_id: str, prod_id: str | None = None
    ) -> dict[str, Any]:
        """PowerSwitch = 1."""
        return await self.set_property(
            device_id, SID_POWER_SWITCH, SID_POWER_SWITCH, SWITCH_ON_VALUE, prod_id
        )

    async def turn_off(
        self, device_id: str, prod_id: str | None = None
    ) -> dict[str, Any]:
        """PowerSwitch = 0."""
        return await self.set_property(
            device_id, SID_POWER_SWITCH, SID_POWER_SWITCH, SWITCH_OFF_VALUE, prod_id
        )

    async def set_fan_level(
        self, device_id: str, level: int, prod_id: str | None = None
    ) -> dict[str, Any]:
        """FanLevel 0-3. Rejects out-of-range locally."""
        if not FAN_LEVEL_STANDBY <= level <= FAN_LEVEL_HIGH:
            raise ValueError(
                f"FanLevel must be {FAN_LEVEL_STANDBY}-{FAN_LEVEL_HIGH}, got {level}"
            )
        return await self.set_property(
            device_id, SID_FAN_LEVEL, SID_FAN_LEVEL, level, prod_id
        )

    async def set_light(
        self, device_id: str, on: bool, prod_id: str | None = None
    ) -> dict[str, Any]:
        """Light = 1/0."""
        return await self.set_property(
            device_id,
            SID_LIGHT,
            SID_LIGHT,
            SWITCH_ON_VALUE if on else SWITCH_OFF_VALUE,
            prod_id,
        )

    # ---- teardown ----

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
