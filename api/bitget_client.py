import requests

BITGET_BASE_URL = "https://api.bitget.com"

INTERVAL_MAP = {
    "1": "1m", "3": "3m", "5": "5m",
    "15": "15m", "30": "30m", "60": "1H"
}


def get_klines(symbol: str, interval: str, limit: int = 2):
    url = f"{BITGET_BASE_URL}/api/v2/mix/market/candles"
    params = {
        "symbol": symbol,
        "granularity": INTERVAL_MAP.get(interval, "5m"),
        "limit": limit,
        "productType": "USDT-FUTURES"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("code") != "00000":
            return None
        return sorted(data["data"], key=lambda x: int(x[0]), reverse=True)
    except Exception:
        return None


def get_futures_tickers():
    url = f"{BITGET_BASE_URL}/api/v2/mix/market/tickers"
    params = {"productType": "USDT-FUTURES"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("code") != "00000":
            return []
        return data["data"]
    except Exception:
        return []


def get_usdt_symbols(limit: int = 20):
    tickers = get_futures_tickers()
    usdt = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt.sort(key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)
    return [t["symbol"] for t in usdt[:limit]]


def get_spot_tickers():
    url = f"{BITGET_BASE_URL}/api/v2/spot/market/tickers"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") != "00000":
            return {}
        result = {}
        for t in data["data"]:
            try:
                result[t["symbol"]] = float(t.get("lastPr", 0))
            except (ValueError, TypeError):
                continue
        return result
    except Exception:
        return {}


def get_spot_symbols(limit: int = 20):
    url = f"{BITGET_BASE_URL}/api/v2/spot/market/tickers"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") != "00000":
            return []
        usdt = [t for t in data["data"] if t["symbol"].endswith("USDT")]
        usdt.sort(key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)
        return [t["symbol"] for t in usdt[:limit]]
    except Exception:
        return []


def get_orderbook(symbol: str, limit: int = 150):
    url = f"{BITGET_BASE_URL}/api/v2/spot/market/orderbook"
    params = {"symbol": symbol, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("code") != "00000":
            return None
        return {
            "a": data["data"].get("asks", []),
            "b": data["data"].get("bids", [])
        }
    except Exception:
        return None


def get_all_funding_rates():
    tickers = get_futures_tickers()
    result = []
    for t in tickers:
        if not t["symbol"].endswith("USDT"):
            continue
        try:
            fr = float(t.get("fundingRate", 0))
            result.append({
                "symbol": t["symbol"],
                "funding_rate": fr,
            })
        except (ValueError, TypeError):
            continue
    return result