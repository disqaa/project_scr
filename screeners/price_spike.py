from api.bybit_client import get_klines, get_usdt_symbols


def check_price_spike(threshold_pct: float, interval: str, symbols_limit: int = 40):
    """
    Ищет монеты с резким изменением цены.
    threshold_pct: минимальный % изменения, например 5.0
    interval: интервал свечи ('1', '5', '15' и т.д.)
    Возвращает список словарей с информацией о сигналах.
    """
    symbols = get_usdt_symbols(symbols_limit)
    alerts = []

    for symbol in symbols:
        klines = get_klines(symbol, interval, limit=2)
        if not klines or len(klines) < 2:
            continue
        try:
            # klines[0] — текущая свеча, klines[1] — предыдущая
            current_close = float(klines[0][4])
            prev_close = float(klines[1][4])

            if prev_close == 0:
                continue

            pct_change = ((current_close - prev_close) / prev_close) * 100

            if abs(pct_change) >= threshold_pct:
                alerts.append({
                    "symbol": symbol,
                    "pct_change": round(pct_change, 2),
                    "current_price": current_close,
                    "direction": "🚀 ВВЕРХ" if pct_change > 0 else "🔻 ВНИЗ"
                })
        except (ValueError, IndexError):
            continue

    return sorted(alerts, key=lambda x: abs(x["pct_change"]), reverse=True)