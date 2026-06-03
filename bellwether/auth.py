"""CoinEx v2 authenticated access — READ-ONLY by design.

Connects Bellwether to *your* CoinEx account to read real balances and open
positions. Signing per CoinEx v2:

    X-COINEX-SIGN = lower_hex( HMAC_SHA256(secret_key, METHOD + request_path + body + timestamp_ms) )

Credentials come from env vars (COINEX_ACCESS_ID / COINEX_SECRET_KEY) or a
local file at ~/.bellwether/credentials.json (chmod 600, never committed).

SAFETY: this module exposes only GET (read) endpoints. It cannot place, modify,
or cancel orders. Live order execution is intentionally NOT implemented here —
that is real money and must be a separate, explicit, confirmed opt-in.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CRED_PATH = Path.home() / ".bellwether" / "credentials.json"
BASE = "https://api.coinex.com"


class AuthError(Exception):
    """Raised for missing credentials or a rejected authenticated request."""


def load_credentials() -> tuple[str | None, str | None]:
    access = os.environ.get("COINEX_ACCESS_ID")
    secret = os.environ.get("COINEX_SECRET_KEY")
    if access and secret:
        return access, secret
    if CRED_PATH.exists():
        try:
            d = json.loads(CRED_PATH.read_text())
            return d.get("access_id"), d.get("secret_key")
        except Exception:
            return None, None
    return None, None


def save_credentials(access_id: str, secret_key: str) -> Path:
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps({"access_id": access_id, "secret_key": secret_key}, indent=2))
    os.chmod(CRED_PATH, 0o600)  # owner read/write only
    return CRED_PATH


def remove_credentials() -> bool:
    if CRED_PATH.exists():
        CRED_PATH.unlink()
        return True
    return False


def has_credentials() -> bool:
    a, s = load_credentials()
    return bool(a and s)


def _sign(secret: str, method: str, request_path: str, body: str, ts: int) -> str:
    prepared = f"{method}{request_path}{body}{ts}"
    return hmac.new(secret.encode(), prepared.encode(), hashlib.sha256).hexdigest()


def _private_get(path: str, params: dict | None = None, timeout: int = 12):
    access, secret = load_credentials()
    if not access or not secret:
        raise AuthError("No CoinEx API credentials. Run `bellwether auth login`.")

    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request_path = f"{path}{query}"
    ts = int(time.time() * 1000)
    sign = _sign(secret, "GET", request_path, "", ts)
    req = urllib.request.Request(
        BASE + request_path,
        headers={
            "X-COINEX-KEY": access,
            "X-COINEX-SIGN": sign,
            "X-COINEX-TIMESTAMP": str(ts),
            "Content-Type": "application/json",
            "User-Agent": "bellwether",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            raise AuthError(f"HTTP {exc.code} from CoinEx.") from exc
    except Exception as exc:
        raise AuthError(f"Request failed: {exc}") from exc

    if payload.get("code") != 0:
        raise AuthError(payload.get("message", "authenticated request rejected"))
    return payload.get("data")


def futures_balance() -> list[dict]:
    """Real futures-account balances: [{ccy, available, frozen, margin, ...}]."""
    data = _private_get("/v2/assets/futures/balance")
    return data if isinstance(data, list) else [data] if data else []


def futures_positions() -> list[dict]:
    """Current open futures positions."""
    data = _private_get("/v2/futures/pending-position", {"market_type": "FUTURES"})
    return data if isinstance(data, list) else [data] if data else []


def account_snapshot() -> dict:
    """Read-only snapshot used by the dashboard. Returns {error: ...} on failure
    so the UI can show a friendly message instead of crashing."""
    try:
        balances = futures_balance()
    except AuthError as exc:
        return {"error": str(exc)}
    positions = []
    try:
        positions = futures_positions()
    except AuthError:
        pass  # balances still useful even if positions endpoint differs

    usdt = next((b for b in balances if str(b.get("ccy")).upper() == "USDT"), None)
    equity = 0.0
    if usdt:
        equity = float(usdt.get("available") or 0) + float(usdt.get("frozen") or 0) + float(usdt.get("margin") or 0)
    return {"balances": balances, "positions": positions, "equity_usdt": equity, "error": None}
