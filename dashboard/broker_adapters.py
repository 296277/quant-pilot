"""Read-only adapters for external simulated trading accounts.

Credentials can stay in process memory or be persisted with Windows DPAPI for
the current Windows user. Secret values are never returned by the catalog, and
this module deliberately exposes no live-order path.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OKX_DEMO_URL = "https://www.okx.com"
CREDENTIAL_FILE = Path(__file__).resolve().parents[1] / "data" / "processed" / "terminal" / "broker_credentials.bin"
_RUNTIME_CONFIG: dict[str, dict[str, str]] = {}
_PERSISTED_PROVIDERS: set[str] = set()
_PERSISTENT_LOADED = False
_CONFIG_LOCK = threading.Lock()


PROVIDER_FIELDS = {
    "miniqmt": ("userdata_path", "account_id"),
    "okx_demo": ("api_key", "secret_key", "passphrase"),
}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _input_blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _protect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("本地加密保存仅支持 Windows")
    source, source_buffer = _input_blob(data)
    entropy, entropy_buffer = _input_blob(b"quant-dashboard-broker-v1")
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    protect = crypt32.CryptProtectData
    protect.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    protect.restype = wintypes.BOOL
    if not protect(ctypes.byref(source), "Quant Dashboard", ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(output.pbData)


def _unprotect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("本地加密读取仅支持 Windows")
    source, source_buffer = _input_blob(data)
    entropy, entropy_buffer = _input_blob(b"quant-dashboard-broker-v1")
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    unprotect.restype = wintypes.BOOL
    if not unprotect(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(output.pbData)


def _ensure_persistent_loaded() -> None:
    global _PERSISTENT_LOADED
    with _CONFIG_LOCK:
        if _PERSISTENT_LOADED:
            return
        _PERSISTENT_LOADED = True
        if not CREDENTIAL_FILE.exists():
            return
        try:
            payload = json.loads(_unprotect_bytes(CREDENTIAL_FILE.read_bytes()).decode("utf-8"))
            for provider, values in payload.items():
                fields = PROVIDER_FIELDS.get(provider)
                if fields and all(isinstance(values.get(field), str) and values[field] for field in fields):
                    _RUNTIME_CONFIG[provider] = {field: values[field] for field in fields}
                    _PERSISTED_PROVIDERS.add(provider)
        except Exception:
            # A corrupted or other-user DPAPI blob is ignored but never overwritten
            # until the user explicitly saves or clears a provider.
            return


def _save_persistent_locked() -> None:
    payload = {provider: _RUNTIME_CONFIG[provider] for provider in _PERSISTED_PROVIDERS if provider in _RUNTIME_CONFIG}
    if not payload:
        if CREDENTIAL_FILE.exists():
            CREDENTIAL_FILE.unlink()
        return
    CREDENTIAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _protect_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    temporary = CREDENTIAL_FILE.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(CREDENTIAL_FILE)


def _runtime_value(provider: str, field: str, environment_name: str) -> str:
    _ensure_persistent_loaded()
    with _CONFIG_LOCK:
        runtime = _RUNTIME_CONFIG.get(provider, {}).get(field, "")
    return runtime or os.environ.get(environment_name, "").strip()


def broker_catalog(local_account: dict[str, Any]) -> dict[str, Any]:
    _ensure_persistent_loaded()
    mini_required = ["MINI_QMT_USERDATA_PATH", "MINI_QMT_ACCOUNT_ID"]
    okx_required = ["OKX_DEMO_API_KEY", "OKX_DEMO_SECRET_KEY", "OKX_DEMO_PASSPHRASE"]
    return {
        "default": "local",
        "items": [
            {
                "id": "local",
                "name": "本地模拟",
                "market": "A 股 / 虚拟货币",
                "configured": True,
                "connected": bool(local_account.get("exists")),
                "read_only": False,
                "mode": "历史回放",
                "requirements": [],
            },
            {
                "id": "miniqmt",
                "name": "miniQMT",
                "market": "A 股",
                "configured": bool(_runtime_value("miniqmt", "userdata_path", mini_required[0]) and _runtime_value("miniqmt", "account_id", mini_required[1])),
                "connected": False,
                "read_only": True,
                "mode": "账户同步（只读）",
                "requirements": mini_required,
                "fields": [
                    {"id": "userdata_path", "label": "QMT 用户数据目录", "type": "text", "placeholder": "例如 D:\\QMT\\userdata_mini"},
                    {"id": "account_id", "label": "资金账号", "type": "text", "placeholder": "输入 miniQMT 账户号"},
                ],
                "stored_locally": "miniqmt" in _PERSISTED_PROVIDERS,
            },
            {
                "id": "okx_demo",
                "name": "OKX Demo",
                "market": "虚拟货币",
                "configured": bool(_runtime_value("okx_demo", "api_key", okx_required[0]) and _runtime_value("okx_demo", "secret_key", okx_required[1]) and _runtime_value("okx_demo", "passphrase", okx_required[2])),
                "connected": False,
                "read_only": False,
                "mode": "官方模拟盘（需确认下单）",
                "requirements": okx_required,
                "fields": [
                    {"id": "api_key", "label": "Demo API Key", "type": "password", "placeholder": "输入 OKX Demo API Key"},
                    {"id": "secret_key", "label": "Demo Secret Key", "type": "password", "placeholder": "输入 OKX Demo Secret Key"},
                    {"id": "passphrase", "label": "Demo Passphrase", "type": "password", "placeholder": "输入 OKX Demo Passphrase"},
                ],
                "stored_locally": "okx_demo" in _PERSISTED_PROVIDERS,
            },
        ],
    }


def configure_broker(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_persistent_loaded()
    provider = str(payload.get("provider") or "")
    if provider not in PROVIDER_FIELDS:
        raise ValueError("不支持的外部交易平台")
    if payload.get("action") == "clear":
        with _CONFIG_LOCK:
            _RUNTIME_CONFIG.pop(provider, None)
            _PERSISTED_PROVIDERS.discard(provider)
            _save_persistent_locked()
        return {"provider": provider, "configured": False, "stored_locally": False}
    values: dict[str, str] = {}
    for field in PROVIDER_FIELDS[provider]:
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ValueError("请填写全部必填信息")
        if len(value) > 512:
            raise ValueError("配置信息过长")
        values[field] = value
    if provider == "miniqmt" and not Path(values["userdata_path"]).is_dir():
        raise ValueError("QMT 用户数据目录不存在，请检查路径")
    with _CONFIG_LOCK:
        _RUNTIME_CONFIG[provider] = values
        if bool(payload.get("persist", True)):
            _PERSISTED_PROVIDERS.add(provider)
        else:
            _PERSISTED_PROVIDERS.discard(provider)
        _save_persistent_locked()
        stored_locally = provider in _PERSISTED_PROVIDERS
    return {"provider": provider, "configured": True, "storage": "windows_dpapi" if stored_locally else "process_memory", "stored_locally": stored_locally}


def _okx_request(
    path: str,
    query: dict[str, str] | None = None,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_key = _runtime_value("okx_demo", "api_key", "OKX_DEMO_API_KEY")
    secret = _runtime_value("okx_demo", "secret_key", "OKX_DEMO_SECRET_KEY")
    passphrase = _runtime_value("okx_demo", "passphrase", "OKX_DEMO_PASSPHRASE")
    if not all((api_key, secret, passphrase)):
        raise ValueError("未配置 OKX Demo 环境变量")
    query_string = urllib.parse.urlencode(query or {})
    request_path = path + (f"?{query_string}" if query_string else "")
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise ValueError("OKX 适配器只允许 GET 和 POST")
    body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    signature = base64.b64encode(
        hmac.new(secret.encode(), f"{timestamp}{method}{request_path}{body_text}".encode(), hashlib.sha256).digest()
    ).decode()
    request = urllib.request.Request(
        OKX_DEMO_URL + request_path,
        data=body_text.encode("utf-8") if body_text else None,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Quant-Research-Console/1.0",
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "x-simulated-trading": "1",
        },
    )
    payload = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_okx_http_error_message(exc)) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    if payload is None:
        proxies = urllib.request.getproxies()
        proxy_url = proxies.get("https") or proxies.get("http") or ""
        proxy_hint = ""
        if proxy_url:
            try:
                parsed_proxy = urllib.parse.urlparse(proxy_url)
                endpoint = parsed_proxy.hostname or "本机代理"
                if parsed_proxy.port:
                    endpoint += f":{parsed_proxy.port}"
                proxy_hint = f" 当前 HTTPS 请求经过代理 {endpoint}，请在 Clash/代理软件中切换可访问 OKX 的节点或规则后重试。"
            except ValueError:
                proxy_hint = " 当前启用了 HTTPS 代理，请检查代理节点是否允许访问 OKX。"
        raise RuntimeError(f"无法连接 OKX 官方 API；公开接口也不可达。{proxy_hint}".strip()) from last_error
    if str(payload.get("code", "0")) != "0":
        raise RuntimeError(payload.get("msg") or "OKX Demo 请求失败")
    return payload


def okx_public_candles(inst_id: str, *, limit: int = 300) -> list[dict[str, Any]]:
    instrument = str(inst_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}-USDT", instrument):
        raise ValueError("仅支持 USDT 现货，例如 BTC-USDT")
    query = urllib.parse.urlencode({"instId": instrument, "bar": "1D", "limit": str(min(max(limit, 220), 300))})
    request = urllib.request.Request(
        f"{OKX_DEMO_URL}/api/v5/market/history-candles?{query}",
        headers={"Accept": "application/json", "User-Agent": "Quant-Research-Console/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if str(payload.get("code", "0")) != "0":
        raise RuntimeError(payload.get("msg") or "OKX K 线请求失败")
    rows = []
    for item in payload.get("data") or []:
        if len(item) < 9 or str(item[8]) != "1":
            continue
        rows.append({
            "timestamp": int(item[0]),
            "open": _number(item[1]),
            "high": _number(item[2]),
            "low": _number(item[3]),
            "close": _number(item[4]),
            "volume": _number(item[5]),
        })
    rows.sort(key=lambda row: row["timestamp"])
    if len(rows) < 220:
        raise RuntimeError(f"OKX 已完成日线不足 220 根，当前 {len(rows)} 根")
    return rows


def okx_demo_place_order(payload: dict[str, Any]) -> dict[str, Any]:
    instrument = str(payload.get("inst_id") or "").strip().upper()
    side = str(payload.get("side") or "").strip().lower()
    if not re.fullmatch(r"[A-Z0-9]{2,12}-USDT", instrument):
        raise ValueError("仅支持 USDT 现货，例如 BTC-USDT")
    if side not in {"buy", "sell"}:
        raise ValueError("方向只能是 buy 或 sell")
    try:
        size = float(payload.get("size"))
    except (TypeError, ValueError) as exc:
        raise ValueError("请输入有效下单数量") from exc
    if not 0 < size <= 100_000:
        raise ValueError("单笔数量必须大于 0 且不超过 100000")
    if payload.get("confirmation") != "OKX_DEMO_ONLY":
        raise ValueError("请先确认这是 OKX Demo 模拟订单")
    order = {
        "instId": instrument,
        "tdMode": "cash",
        "side": side,
        "ordType": "market",
        "sz": format(size, ".12g"),
        "tgtCcy": "quote_ccy" if side == "buy" else "base_ccy",
    }
    result = _okx_request("/api/v5/trade/order", method="POST", body=order)
    item = (result.get("data") or [{}])[0]
    if str(item.get("sCode", "0")) != "0":
        raise RuntimeError(item.get("sMsg") or "OKX Demo 下单失败")
    return {
        "provider": "okx_demo",
        "demo": True,
        "inst_id": instrument,
        "side": side,
        "size": size,
        "order_id": item.get("ordId"),
        "message": item.get("sMsg") or "模拟订单已提交",
    }


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _okx_http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        code = str(payload.get("code") or exc.code)
        message = str(payload.get("msg") or "鉴权失败")
        guidance = {
            "50101": "API Key 与模拟环境不匹配；请使用 Demo Trading 页面创建的模拟 API Key",
            "50105": "API Passphrase 不正确",
            "50110": "当前公网 IP 不在 API 白名单中",
            "50111": "API Key 无效或不存在",
            "50113": "签名校验失败，请重新核对 Secret Key",
        }.get(code)
        return f"OKX {code}：{guidance or message}"
    except Exception:
        return f"OKX 返回 HTTP {exc.code}，请检查 API 所属地区和访问权限"


def okx_demo_snapshot() -> dict[str, Any]:
    balance = _okx_request("/api/v5/account/balance")
    positions = _okx_request("/api/v5/account/positions")
    orders = _okx_request("/api/v5/trade/orders-pending")
    fills = _okx_request("/api/v5/trade/fills-history", {"instType": "SPOT", "limit": "50"})
    account = (balance.get("data") or [{}])[0]
    details = account.get("details") or []
    currencies = [
        {
            "currency": item.get("ccy"),
            "equity": _number(item.get("eq")),
            "available": _number(item.get("availEq") or item.get("availBal")),
            "unrealized_pnl": _number(item.get("upl")),
        }
        for item in details
        if abs(_number(item.get("eq"))) > 1e-12
    ]
    return {
        "provider": "okx_demo",
        "name": "OKX Demo",
        "mode": "官方模拟盘",
        "read_only": False,
        "connected": True,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "equity_usd": _number(account.get("totalEq")),
            "available_usd": sum(item["available"] for item in currencies if item["currency"] in {"USD", "USDT", "USDC"}),
            "unrealized_pnl": sum(item["unrealized_pnl"] for item in currencies),
        },
        "balances": currencies,
        "positions": positions.get("data") or [],
        "orders": orders.get("data") or [],
        "fills": fills.get("data") or [],
        "notice": "强制使用 OKX 模拟交易请求头；支持需二次确认的现货市价模拟订单，绝不发送实盘。",
    }


def miniqmt_snapshot() -> dict[str, Any]:
    userdata = Path(_runtime_value("miniqmt", "userdata_path", "MINI_QMT_USERDATA_PATH"))
    account_id = _runtime_value("miniqmt", "account_id", "MINI_QMT_ACCOUNT_ID")
    if not userdata.is_dir() or not account_id:
        raise ValueError("未配置有效的 MINI_QMT_USERDATA_PATH 和 MINI_QMT_ACCOUNT_ID")
    try:
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount
    except ImportError as exc:
        raise RuntimeError("当前 Python 环境未找到 xtquant，请使用券商 miniQMT 自带库") from exc

    session_id = int(time.time() * 1000) % 2_000_000_000
    trader = XtQuantTrader(str(userdata), session_id)
    trader.start()
    try:
        if trader.connect() != 0:
            raise RuntimeError("miniQMT 客户端连接失败，请确认 QMT 已启动并登录")
        account = StockAccount(account_id)
        if trader.subscribe(account) != 0:
            raise RuntimeError("miniQMT 账户订阅失败，请核对账户号和权限")
        asset = trader.query_stock_asset(account)
        positions = trader.query_stock_positions(account) or []
        orders = trader.query_stock_orders(account) or []
        trades = trader.query_stock_trades(account) or []
        return {
            "provider": "miniqmt",
            "name": "miniQMT",
            "mode": "A 股账户同步",
            "read_only": True,
            "connected": True,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
            "summary": {
                "equity": _number(getattr(asset, "total_asset", 0)),
                "cash": _number(getattr(asset, "cash", 0)),
                "market_value": _number(getattr(asset, "market_value", 0)),
            },
            "positions": [vars(item) for item in positions],
            "orders": [vars(item) for item in orders],
            "fills": [vars(item) for item in trades],
            "notice": "当前仅同步账户数据，不调用 miniQMT 委托接口。",
        }
    finally:
        stop = getattr(trader, "stop", None)
        if callable(stop):
            stop()


def sync_broker(provider: str) -> dict[str, Any]:
    if provider == "okx_demo":
        return okx_demo_snapshot()
    if provider == "miniqmt":
        return miniqmt_snapshot()
    raise ValueError("不支持的外部交易平台")
