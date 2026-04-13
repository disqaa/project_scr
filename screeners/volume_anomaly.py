from api.bybit_client import get_klines, get_usdt_symbols


def check_volume_anomaly(multiplier: float, interval: str, lookback: int = 10, symbols_limit: int = 40):

    symbols = get_usdt_symbols(symbols_limit)
    alerts = []

    for symbol in symbols:
        klines = get_klines(symbol, interval, limit=lookback + 1)
        if not klines or len(klines) < lookback + 1:
            continue
        try:
            current_volume = float(klines[0][5])
            prev_volumes = [float(k[5]) for k in klines[1:]]
            avg_volume = sum(prev_volumes) / len(prev_volumes)

            if avg_volume == 0:
                continue

            ratio = current_volume / avg_volume

            if ratio >= multiplier:
                alerts.append({
                    "symbol": symbol,
                    "volume_ratio": round(ratio, 2),
                    "current_volume": round(current_volume, 2),
                    "avg_volume": round(avg_volume, 2),
                    "current_price": float(klines[0][4])
                })
        except (ValueError, IndexError):
            continue

    return sorted(alerts, key=lambda x: x["volume_ratio"], reverse=True)