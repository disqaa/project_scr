from api.bybit_client import get_spot_symbols, get_orderbook, get_spot_tickers


def check_orderbook_walls(min_size_usdt: float, max_distance_pct: float, symbols_limit: int = 30):
    # получаем топ спот-символов по объёму
    symbols = get_spot_symbols(symbols_limit)
    # получаем текущие цены для всех символов сразу
    prices = get_spot_tickers()
    alerts = []

    for symbol in symbols:
        current_price = prices.get(symbol)
        if not current_price or current_price == 0:
            continue

        # запрашиваем стакан — 200 уровней с каждой стороны
        orderbook = get_orderbook(symbol, limit=200)
        if not orderbook:
            continue

        bids = orderbook.get("b", [])  # заявки на покупку [price, size]
        asks = orderbook.get("a", [])  # заявки на продажу [price, size]

        # проверяем биды (заявки на покупку — снизу от цены)
        for bid in bids:
            try:
                price = float(bid[0])
                size = float(bid[1])
                size_usdt = price * size

                if size_usdt < min_size_usdt:
                    continue

                # расстояние от текущей цены до заявки в процентах
                distance_pct = ((current_price - price) / current_price) * 100

                if 0 <= distance_pct <= max_distance_pct:
                    pair = symbol.replace("USDT", "/USDT")
                    alerts.append({
                        "symbol": symbol,
                        "pair": pair,
                        "side": "BID",  # заявка на покупку
                        "wall_price": price,
                        "current_price": current_price,
                        "size_usdt": round(size_usdt, 2),
                        "distance_pct": round(distance_pct, 2),
                    })
            except (ValueError, IndexError):
                continue

        # проверяем аски (заявки на продажу — сверху от цены)
        for ask in asks:
            try:
                price = float(ask[0])
                size = float(ask[1])
                size_usdt = price * size

                if size_usdt < min_size_usdt:
                    continue

                distance_pct = ((price - current_price) / current_price) * 100

                if 0 <= distance_pct <= max_distance_pct:
                    pair = symbol.replace("USDT", "/USDT")
                    alerts.append({
                        "symbol": symbol,
                        "pair": pair,
                        "side": "ASK",  # заявка на продажу
                        "wall_price": price,
                        "current_price": current_price,
                        "size_usdt": round(size_usdt, 2),
                        "distance_pct": round(distance_pct, 2),
                    })
            except (ValueError, IndexError):
                continue

    # сортируем по размеру заявки — самые крупные первыми
    return sorted(alerts, key=lambda x: x["size_usdt"], reverse=True)