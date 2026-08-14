from __future__ import annotations

import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from dashboard import broker_adapters


class BrokerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.credential_directory = tempfile.TemporaryDirectory()
        isolated_file = Path(self.credential_directory.name) / "broker_credentials.bin"
        self.credential_patch = patch.object(broker_adapters, "CREDENTIAL_FILE", isolated_file)
        self.credential_patch.start()
        broker_adapters._RUNTIME_CONFIG.clear()
        broker_adapters._PERSISTED_PROVIDERS.clear()
        broker_adapters._PERSISTENT_LOADED = True

    def tearDown(self) -> None:
        broker_adapters._RUNTIME_CONFIG.clear()
        broker_adapters._PERSISTED_PROVIDERS.clear()
        broker_adapters._PERSISTENT_LOADED = False
        self.credential_patch.stop()
        self.credential_directory.cleanup()

    def test_catalog_does_not_expose_secret_values(self) -> None:
        env = {
            "OKX_DEMO_API_KEY": "secret-key",
            "OKX_DEMO_SECRET_KEY": "secret-value",
            "OKX_DEMO_PASSPHRASE": "secret-passphrase",
        }
        with patch.dict(os.environ, env, clear=True):
            catalog = broker_adapters.broker_catalog({"exists": False})
        serialized = str(catalog)
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("secret-value", serialized)
        okx = next(item for item in catalog["items"] if item["id"] == "okx_demo")
        self.assertTrue(okx["configured"])
        self.assertFalse(okx["read_only"])
        self.assertIn("需确认下单", okx["mode"])

    def test_okx_request_forces_demo_header(self) -> None:
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":"0","data":[]}'
        env = {
            "OKX_DEMO_API_KEY": "key",
            "OKX_DEMO_SECRET_KEY": "secret",
            "OKX_DEMO_PASSPHRASE": "passphrase",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(broker_adapters.urllib.request, "urlopen", return_value=response) as request:
            broker_adapters._okx_request("/api/v5/account/balance")
        sent = request.call_args.args[0]
        self.assertEqual(sent.headers["X-simulated-trading"], "1")

    def test_okx_network_reset_returns_actionable_proxy_message(self) -> None:
        env = {
            "OKX_DEMO_API_KEY": "key",
            "OKX_DEMO_SECRET_KEY": "secret",
            "OKX_DEMO_PASSPHRASE": "passphrase",
        }
        reset = urllib.error.URLError(ConnectionResetError(10054, "connection reset"))
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(broker_adapters.urllib.request, "urlopen", side_effect=reset),
            patch.object(broker_adapters.urllib.request, "getproxies", return_value={"https": "http://127.0.0.1:7890"}),
            patch.object(broker_adapters.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "127.0.0.1:7890"):
                broker_adapters._okx_request("/api/v5/account/balance")

    def test_okx_http_error_exposes_official_code_without_secrets(self) -> None:
        response = unittest.mock.MagicMock()
        response.code = 401
        response.read.return_value = b'{"code":"50113","msg":"Invalid Sign"}'
        message = broker_adapters._okx_http_error_message(response)
        self.assertIn("50113", message)
        self.assertIn("Secret Key", message)
        self.assertNotIn("Invalid Sign", message)

    def test_okx_environment_mismatch_points_to_demo_key(self) -> None:
        response = unittest.mock.MagicMock()
        response.code = 401
        response.read.return_value = b'{"code":"50101","msg":"APIKey does not match current environment."}'
        message = broker_adapters._okx_http_error_message(response)
        self.assertIn("Demo Trading", message)

    def test_okx_demo_order_requires_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "确认"):
            broker_adapters.okx_demo_place_order({"inst_id": "BTC-USDT", "side": "buy", "size": 10})

    def test_okx_demo_order_posts_only_to_simulated_endpoint(self) -> None:
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":"0","data":[{"ordId":"demo-1","sCode":"0","sMsg":""}]}'
        env = {
            "OKX_DEMO_API_KEY": "key",
            "OKX_DEMO_SECRET_KEY": "secret",
            "OKX_DEMO_PASSPHRASE": "passphrase",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(broker_adapters.urllib.request, "urlopen", return_value=response) as request:
            result = broker_adapters.okx_demo_place_order({"inst_id": "BTC-USDT", "side": "buy", "size": 25, "confirmation": "OKX_DEMO_ONLY"})
        sent = request.call_args.args[0]
        self.assertEqual(sent.method, "POST")
        self.assertEqual(sent.headers["X-simulated-trading"], "1")
        self.assertIn(b'"instId":"BTC-USDT"', sent.data)
        self.assertTrue(result["demo"])

    def test_external_sync_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ValueError):
            broker_adapters.sync_broker("live")

    def test_runtime_okx_configuration_is_memory_only(self) -> None:
        broker_adapters.configure_broker({
            "provider": "okx_demo",
            "api_key": "runtime-key",
            "secret_key": "runtime-secret",
            "passphrase": "runtime-passphrase",
            "persist": False,
        })
        try:
            catalog = broker_adapters.broker_catalog({"exists": False})
            serialized = str(catalog)
            self.assertTrue(next(item for item in catalog["items"] if item["id"] == "okx_demo")["configured"])
            self.assertNotIn("runtime-key", serialized)
            self.assertNotIn("runtime-secret", serialized)
        finally:
            broker_adapters.configure_broker({"provider": "okx_demo", "action": "clear"})

    def test_miniqmt_configuration_rejects_missing_directory(self) -> None:
        with self.assertRaises(ValueError):
            broker_adapters.configure_broker({
                "provider": "miniqmt",
                "userdata_path": "Z:/missing/userdata_mini",
                "account_id": "123456",
            })

    def test_persistent_configuration_is_encrypted_and_reloadable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials.bin"
            with (
                patch.object(broker_adapters, "CREDENTIAL_FILE", path),
                patch.object(broker_adapters, "_protect_bytes", side_effect=lambda value: b"encrypted:" + value[::-1]),
                patch.object(broker_adapters, "_unprotect_bytes", side_effect=lambda value: value.removeprefix(b"encrypted:")[::-1]),
            ):
                broker_adapters._RUNTIME_CONFIG.clear()
                broker_adapters._PERSISTED_PROVIDERS.clear()
                broker_adapters._PERSISTENT_LOADED = True
                result = broker_adapters.configure_broker({"provider": "okx_demo", "api_key": "saved-key", "secret_key": "saved-secret", "passphrase": "saved-pass", "persist": True})
                self.assertTrue(result["stored_locally"])
                self.assertNotIn(b"saved-key", path.read_bytes())
                broker_adapters._RUNTIME_CONFIG.clear()
                broker_adapters._PERSISTED_PROVIDERS.clear()
                broker_adapters._PERSISTENT_LOADED = False
                catalog = broker_adapters.broker_catalog({"exists": False})
                okx = next(item for item in catalog["items"] if item["id"] == "okx_demo")
                self.assertTrue(okx["configured"])
                self.assertTrue(okx["stored_locally"])
                broker_adapters.configure_broker({"provider": "okx_demo", "action": "clear"})
                self.assertFalse(path.exists())

    def test_memory_only_choice_removes_previously_saved_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials.bin"
            with (
                patch.object(broker_adapters, "CREDENTIAL_FILE", path),
                patch.object(broker_adapters, "_protect_bytes", side_effect=lambda value: b"encrypted:" + value[::-1]),
                patch.object(broker_adapters, "_unprotect_bytes", side_effect=lambda value: value.removeprefix(b"encrypted:")[::-1]),
            ):
                broker_adapters._RUNTIME_CONFIG.clear()
                broker_adapters._PERSISTED_PROVIDERS.clear()
                broker_adapters._PERSISTENT_LOADED = True
                values = {"provider": "okx_demo", "api_key": "key", "secret_key": "secret", "passphrase": "pass"}
                broker_adapters.configure_broker({**values, "persist": True})
                self.assertTrue(path.exists())
                result = broker_adapters.configure_broker({**values, "persist": False})
                self.assertFalse(result["stored_locally"])
                self.assertFalse(path.exists())
                catalog = broker_adapters.broker_catalog({"exists": False})
                okx = next(item for item in catalog["items"] if item["id"] == "okx_demo")
                self.assertTrue(okx["configured"])
                self.assertFalse(okx["stored_locally"])
                broker_adapters.configure_broker({"provider": "okx_demo", "action": "clear"})


if __name__ == "__main__":
    unittest.main()
