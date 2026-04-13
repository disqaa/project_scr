from api.bybit_client import get_all_funding_rates


def check_funding_rate(threshold: float):

    rates = get_all_funding_rates()
    alerts = []

    for r in rates:
        fr = r["funding_rate"]
        if abs(fr) >= threshold:
            alerts.append({
                "symbol": r["symbol"],
                "funding_rate": fr,
                "funding_rate_pct": round(fr * 100, 4),
                "direction": "📈 Лонги платят шортам" if fr > 0 else "📉 Шорты платят лонгам",
                "next_funding_time": r["next_funding_time"]
            })

    return sorted(alerts, key=lambda x: abs(x["funding_rate"]), reverse=True)