"""Tests for dishwasher detection without loading Home Assistant."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).parents[1]
FOTILE = ROOT / "custom_components" / "fotile"


def _install_package(name: str, path: pathlib.Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_package("custom_components", FOTILE.parent)
_install_package("custom_components.fotile", FOTILE)
_install_package("custom_components.fotile.core", FOTILE / "core")
_load_module("custom_components.fotile.const", FOTILE / "const.py")
device_module = _load_module(
    "custom_components.fotile.core.device",
    FOTILE / "core" / "device.py",
)
mapping_module = _load_module(
    "custom_components.fotile.core.mapping",
    FOTILE / "core" / "mapping.py",
)


class DishwasherDetectionTest(unittest.TestCase):
    def test_detects_v6a_from_model(self) -> None:
        device = device_module.FotileDevice(
            {
                "device_id": "123",
                "name": "嵌入式洗碗机V6",
                "model": "JBCD7E-02-V6A",
            }
        )
        self.assertIn("dishwasher", device.kinds)

    def test_detects_unknown_model_from_shadow_fields(self) -> None:
        device = device_module.FotileDevice(
            {
                "device_id": "123",
                "name": "appliance",
                "model": "unknown",
            }
        )
        device.update_status(
            {
                "online": True,
                "_flat": {
                    "AppState.WorkState": 0,
                    "AppState.WorkMode": 0,
                    "AppState.DoorLockSta": 0,
                },
            }
        )
        self.assertIn("dishwasher", device.kinds)

    def test_does_not_classify_unrelated_device(self) -> None:
        device = device_module.FotileDevice(
            {
                "device_id": "123",
                "name": "range hood",
                "model": "unknown",
                "service_ids": ["FanLevel"],
            }
        )
        self.assertNotIn("dishwasher", device.kinds)

    def test_maps_app_device(self) -> None:
        mapped = mapping_module.map_app_device_fields(
            {
                "id": 123,
                "name": "嵌入式洗碗机V6",
                "product_id": "opaque-product-id",
                "type": "JBCD7E-02-V6A",
                "sn": "serial",
            }
        )
        self.assertEqual(mapped["device_id"], "123")
        self.assertEqual(mapped["model"], "JBCD7E-02-V6A")
        self.assertEqual(mapped["product_id"], "opaque-product-id")
        self.assertEqual(mapped["_source"], "app")

    def test_maps_app_shadow(self) -> None:
        mapped = mapping_module.map_app_shadow(
            {
                "online": True,
                "shadowData": {
                    "propertyPairs": {
                        "PowerSwitchAll": 1,
                        "WorkState": 0,
                        "Nested": {"ignored": True},
                    }
                },
            }
        )
        self.assertTrue(mapped["online"])
        self.assertEqual(mapped["_flat"]["AppState.PowerSwitchAll"], 1)
        self.assertEqual(mapped["_flat"]["AppState.WorkState"], 0)
        self.assertNotIn("AppState.Nested", mapped["_flat"])


if __name__ == "__main__":
    unittest.main()
