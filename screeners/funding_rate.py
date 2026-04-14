from api.bybit_client import get_all_funding_rates


def check_funding_rate(threshold: float):
    # получаем ставки для всех фьючерсных пар
    rates = get_all_funding_rates()
    alerts = []

    for r in rates:
        fr = r["funding_rate"]
        if abs(fr) >= threshold:
            pair = r["symbol"].replace("USDT", "/USDT")
            alerts.append({
                "symbol": r["symbol"],
                "pair": pair,
                "funding_rate": fr,
                "funding_rate_pct": round(fr * 100, 4),
                # позитивный фандинг — лонги платят шортам (рынок перегрет вверх)
                "direction": "📈 лонги платят шортам" if fr > 0 else "📉 шорты платят лонгам",
            })

    return sorted(alerts, key=lambda x: abs(x["funding_rate"]), reverse=True)