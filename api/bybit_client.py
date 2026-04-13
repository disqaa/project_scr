import requests
from config import BYBIT_BASE_URL


def get_klines(symbol: str, interval: str, limit: int = 11):
    """
    Получить свечи (OHLCV).
    interval: '1', '3', '5', '15', '30', '60'
    Возвращает список [timestamp, open, high, low, close, volume, turnover]
    Свечи отсортированы от новой к старой (klines[0] — текущая)
    """
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
    """Получить все тикеры с текущими данными."""
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
    """Получить список топ USDT-перп символов по объёму."""
    tickers = get_tickers("linear")
    usdt = [t for t in tickers if t["symbol"].endswith("USDT")]
    # Сортируем по объёму торгов за 24 часа
    usdt.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
    return [t["symbol"] for t in usdt[:limit]]


def get_all_funding_rates():
    """Получить ставки фандинга для всех символов."""
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
                "next_funding_time": t.get("nextFundingTime", "—")
            })
        except (ValueError, TypeError):
            continue
    return result