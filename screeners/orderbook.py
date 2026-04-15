from api.bybit_client import get_spot_symbols, get_orderbook, get_spot_tickers


def fetch_orderbook_walls(min_size_usdt: float, max_distance_pct: float, symbols_limit: int = 20):
    symbols = get_spot_symbols(symbols_limit)
    prices = get_spot_tickers()
    walls = {}

    for symbol in symbols:
        current_price = prices.get(symbol)
        if not current_price or current_price == 0:
            continue

        orderbook = get_orderbook(symbol, limit=200)
        if not orderbook:
            continue

        bids = orderbook.get("b", [])
        asks = orderbook.get("a", [])

        for bid in bids:
            try:
                price = float(bid[0])
                size = float(bid[1])
                size_usdt = price * size

                if size_usdt < min_size_usdt:
                    continue

                distance_pct = ((current_price - price) / current_price) * 100

                if 0 <= distance_pct <= max_distance_pct:
                    key = (symbol, "BID", price)
                    pair = symbol.replace("USDT", "/USDT")
                    walls[key] = {
                        "pair": pair,
                        "side": "BID",
                        "wall_price": price,
                        "current_price": current_price,
                        "size_usdt": round(size_usdt, 2),
                        "distance_pct": round(distance_pct, 2),
                    }
            except (ValueError, IndexError):
                continue

        for ask in asks:
            try:
                price = float(ask[0])
                size = float(ask[1])
                size_usdt = price * size

                if size_usdt < min_size_usdt:
                    continue

                distance_pct = ((price - current_price) / current_price) * 100

                if 0 <= distance_pct <= max_distance_pct:
                    key = (symbol, "ASK", price)
                    pair = symbol.replace("USDT", "/USDT")
                    walls[key] = {
                        "pair": pair,
                        "side": "ASK",
                        "wall_price": price,
                        "current_price": current_price,
                        "size_usdt": round(size_usdt, 2),
                        "distance_pct": round(distance_pct, 2),
                    }
            except (ValueError, IndexError):
                continue

    return walls