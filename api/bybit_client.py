import requests
from config import BYBIT_BASE_URL


def get_klines(symbol: str, interval: str, limit: int = 11):
    # свечи для фьючерсного рынка (linear = usdt-perp)
    url = f"{BYBIT_BASE_URL}/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("retCode") != 0:
            return None
        return data["result"]["list"]
    except Exception:
        return None


def get_tickers(category: str = "linear"):
    # все тикеры с текущими данными
    url = f"{BYBIT_BASE_URL}/v5/market/tickers"
    params = {"category": category}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("retCode") != 0:
            return []
        return data["result"]["list"]
    except Exception:
        return []


def get_usdt_symbols(limit: int = 40):
    # топ фьючерсных символов по обороту за 24 часа
    tickers = get_tickers("linear")
    usdt = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
    return [t["symbol"] for t in usdt[:limit]]


def get_spot_symbols(limit: int = 30):
    # топ спот-символов по обороту за 24 часа
    tickers = get_tickers("spot")
    usdt = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
    return [t["symbol"] for t in usdt[:limit]]


def get_spot_tickers():
    # возвращает словарь {symbol: current_price} для спот рынка
    tickers = get_tickers("spot")
    result = {}
    for t in tickers:
        try:
            result[t["symbol"]] = float(t.get("lastPrice", 0))
        except (ValueError, TypeError):
            continue
    return result


def get_orderbook(symbol: str, limit: int = 200):
    # стакан заявок для спот рынка
    url = f"{BYBIT_BASE_URL}/v5/market/orderbook"
    params = {
        "category": "spot",
        "symbol": symbol,
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("retCode") != 0:
            return None
        return data["result"]
    except Exception:
        return None


def get_all_funding_rates():
    # ставки фандинга для всех фьючерсных символов
    tickers = get_tickers("linear")
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