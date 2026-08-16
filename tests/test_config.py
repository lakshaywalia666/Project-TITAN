from __future__ import annotations

import unittest

from titan_api.config import ConfigurationError, Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_are_local_and_bounded(self) -> None:
        settings = Settings.from_environ({})

        self.assertEqual("127.0.0.1", settings.host)
        self.assertEqual(8080, settings.port)
        self.assertEqual(16_384, settings.max_request_bytes)

    def test_environment_overrides_are_parsed(self) -> None:
        settings = Settings.from_environ(
            {
                "TITAN_HOST": "0.0.0.0",
                "TITAN_PORT": "9090",
                "TITAN_MAX_REQUEST_BYTES": "32768",
            }
        )

        self.assertEqual("0.0.0.0", settings.host)
        self.assertEqual(9090, settings.port)
        self.assertEqual(32_768, settings.max_request_bytes)

    def test_invalid_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "TITAN_PORT"):
            Settings.from_environ({"TITAN_PORT": "70000"})

    def test_request_limit_cannot_be_disabled_with_zero(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "TITAN_MAX_REQUEST_BYTES"):
            Settings.from_environ({"TITAN_MAX_REQUEST_BYTES": "0"})


if __name__ == "__main__":
    unittest.main()

