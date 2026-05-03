from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

SCREENER_EMOJI = {
    "price_spike": "📈",
    "orderbook": "📖",
    "funding_rate": "💰"
}

SCREENER_NAMES = {
    "price_spike": "Price Spike",
    "orderbook": "Order Book Walls",
    "funding_rate": "Funding Rate"
}

EXCHANGE_EMOJI = {
    "bybit": "🟡",
    "bitget": "🔵"
}

INTERVAL_MAP = {
    "1 мин": "1", "3 мин": "3", "5 мин": "5",
    "15 мин": "15", "30 мин": "30", "1 час": "60"
}

INTERVAL_LABELS = {
    "1": "1 мин", "3": "3 мин", "5": "5 мин",
    "15": "15 мин", "30": "30 мин", "60": "1 час"
}


def auth_keyboard():
    return ReplyKeyboardMarkup(
        [["📝 Регистрация", "🔑 Войти"]],
        resize_keyboard=True
    )


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🔍 Запустить скринер", "📋 Мои конфиги"],
            ["📊 Активные скринеры", "ℹ️ Помощь"],
            ["🚪 Выйти из аккаунта"]
        ],
        resize_keyboard=True
    )


def exchange_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🟡 Bybit", "🔵 Bitget"],
            ["◀️ Главное меню"]
        ],
        resize_keyboard=True
    )


def screener_type_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📈 Price Spike"],
            ["📖 Order Book Walls"],
            ["💰 Funding Rate"],
            ["◀️ Главное меню"]
        ],
        resize_keyboard=True
    )


def interval_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["1 мин", "3 мин", "5 мин"],
            ["15 мин", "30 мин", "1 час"],
            ["◀️ Главное меню"]
        ],
        resize_keyboard=True
    )


def save_or_run_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💾 Сохранить и запустить"],
            ["▶️ Запустить без сохранения"],
            ["◀️ Главное меню"]
        ],
        resize_keyboard=True
    )


def back_to_main_keyboard():
    return ReplyKeyboardMarkup(
        [["◀️ Главное меню"]],
        resize_keyboard=True
    )


def configs_inline_keyboard(configs_data: list):
    keyboard = []
    for cid, name, stype, exchange in configs_data:
        emoji = SCREENER_EMOJI.get(stype, "🔍")
        ex_emoji = EXCHANGE_EMOJI.get(exchange, "")
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {name} {ex_emoji}",
            callback_data=f"load_{cid}"
        )])
    keyboard.append([InlineKeyboardButton("🗑 Удалить конфиг", callback_data="delete_menu")])
    return InlineKeyboardMarkup(keyboard)


def delete_inline_keyboard(configs_data: list):
    keyboard = []
    for cid, name, stype, exchange in configs_data:
        keyboard.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"del_{cid}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_configs")])
    return InlineKeyboardMarkup(keyboard)


def manage_screeners_inline_keyboard(active: dict):
    keyboard = []
    all_types = ["price_spike", "orderbook", "funding_rate"]
    for stype in all_types:
        emoji = SCREENER_EMOJI[stype]
        name = SCREENER_NAMES[stype]
        if stype in active:
            exchange = active[stype].get("exchange", "bybit")
            ex_emoji = EXCHANGE_EMOJI.get(exchange, "")
            keyboard.append([InlineKeyboardButton(
                f"🔴 Стоп {emoji} {name} {ex_emoji}",
                callback_data=f"stop_{stype}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                f"⚪ {emoji} {name} — не запущен",
                callback_data="noop"
            )])
    if active:
        keyboard.append([InlineKeyboardButton("🛑 Остановить все скринеры", callback_data="stop_all")])
    keyboard.append([InlineKeyboardButton("✖️ Закрыть", callback_data="close_manage")])
    return InlineKeyboardMarkup(keyboard)