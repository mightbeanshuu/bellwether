"""Real-time price stream over CoinEx's WebSocket.

REST polling can't safely do millisecond updates (you'd be rate-limited within
seconds). Instead we hold one persistent WebSocket and let the exchange *push*
`state.update` frames as the market moves; the dashboard then reads the latest
in-memory price every frame with zero per-frame network cost.

Frames are gzip-compressed binary. The stream runs on a daemon thread and
auto-reconnects, so the UI thread just calls `prices()` whenever it repaints.
"""

from __future__ import annotations

import gzip
import json
import threading
import time

from .data import Quote

WS_URL = {
    "futures": "wss://socket.coinex.com/v2/futures",
    "spot": "wss://socket.coinex.com/v2/spot",
}


class LivePriceStream:
    def __init__(self, markets: list[str], segment: str = "futures"):
        self.markets = list(markets)
        self.segment = "spot" if segment == "coinex-spot" else "futures"
        self._prices: dict[str, Quote] = {}
        self._lock = threading.Lock()
        self._ws = None
        self._stop = False
        self._thread: threading.Thread | None = None
        self.connected = False

    # -- public API ----------------------------------------------------
    def start(self) -> "LivePriceStream":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def prices(self) -> dict[str, Quote]:
        with self._lock:
            return dict(self._prices)

    def stop(self) -> None:
        self._stop = True
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass

    # -- websocket callbacks -------------------------------------------
    def _on_open(self, ws) -> None:
        self.connected = True
        ws.send(json.dumps({
            "method": "state.subscribe",
            "params": {"market_list": self.markets},
            "id": 1,
        }))

    def _on_data(self, ws, message, data_type, cont) -> None:
        if isinstance(message, (bytes, bytearray)):
            try:
                message = gzip.decompress(bytes(message)).decode("utf-8", "replace")
            except Exception:
                return
        try:
            payload = json.loads(message)
        except Exception:
            return
        if payload.get("method") != "state.update":
            return
        states = (payload.get("data") or {}).get("state_list", [])
        with self._lock:
            for s in states:
                try:
                    self._prices[s["market"]] = Quote(
                        symbol=s["market"],
                        last=float(s["last"]),
                        open_24h=float(s.get("open") or 0),
                        high=float(s.get("high") or 0),
                        low=float(s.get("low") or 0),
                        volume=float(s.get("volume") or 0),
                    )
                except (KeyError, ValueError, TypeError):
                    continue

    def _on_close(self, *args) -> None:
        self.connected = False

    def _on_error(self, *args) -> None:
        self.connected = False

    # -- run loop with reconnect ---------------------------------------
    def _run(self) -> None:
        try:
            import websocket  # websocket-client
        except ImportError:
            return  # caller falls back to REST quotes
        while not self._stop:
            try:
                self._ws = websocket.WebSocketApp(
                    WS_URL[self.segment],
                    on_open=self._on_open,
                    on_data=self._on_data,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                pass
            if self._stop:
                break
            time.sleep(1.0)  # reconnect backoff
