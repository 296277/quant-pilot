from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from quant_trading.market_data import fetch_gate_candles


class MarketDataTests(unittest.TestCase):
    def test_gate_candles_use_public_api_without_external_scripts(self) -> None:
        rows = [
            ["1704153600", "2200", "102", "104", "99", "100", "21", "true"],
            ["1704067200", "1000", "100", "101", "97", "98", "10", "true"],
        ]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(rows).encode("utf-8")
        with patch("quant_trading.market_data.urllib.request.urlopen", return_value=response) as request:
            data, payload = fetch_gate_candles("1d", 300, symbol="BTC")
        sent = request.call_args.args[0]
        self.assertIn("api.gateio.ws/api/v4/spot/candlesticks", sent.full_url)
        self.assertIn("currency_pair=BTC_USDT", sent.full_url)
        self.assertEqual(data["close"].tolist(), [100.0, 102.0])
        self.assertEqual(data["open"].tolist(), [98.0, 100.0])
        self.assertEqual(payload["source"], "gate.io")


if __name__ == "__main__":
    unittest.main()
