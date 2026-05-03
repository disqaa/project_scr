from api.bybit_client import get_klines, get_usdt_symbols


def check_price_spike(threshold_pct: float, interval: str, client, symbols_limit: int = 20):
    symbols = client.get_usdt_symbols(symbols_limit)
    alerts = []
    for symbol in symbols:
        klines = client.get_klines(symbol, interval, limit=2)
        if not klines or len(klines) < 2:
            continue
        try:
            current_close = float(klines[0][4])
            prev_close = float(klines[1][4])
            if prev_close == 0:
                continue
            pct_change = ((current_close - prev_close) / prev_close) * 100
            if abs(pct_change) >= threshold_pct:
                pair = symbol.replace("USDT", "/USDT")
                alerts.append({
                    "symbol": symbol,
                    "pair": pair,
                    "pct_change": round(pct_change, 2),
                    "price_from": prev_close,
                    "price_to": current_close,
                    "is_pump": pct_change > 0,
                })
        except (ValueError, IndexError):
            continue
    return sorted(alerts, key=lambda x: abs(x["pct_change"]), reverse=True)