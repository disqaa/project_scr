from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

#Reply-клавиатуры

def auth_keyboard():
    return ReplyKeyboardMarkup(
        [["📝 Регистрация", "🔑 Войти"]],
        resize_keyboard=True
    )


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🔍 Запустить скринер", "📋 Мои конфиги"],
            ["🛑 Остановить скринер", "ℹ️ Помощь"],
            ["🚪 Выйти из аккаунта"]
        ],
        resize_keyboard=True
    )


def screener_type_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📈 Price Spike"],
            ["📊 Volume Anomaly"],
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


#Inline-клавиатуры

SCREENER_EMOJI = {
    "price_spike": "📈",
    "volume_anomaly": "📊",
    "funding_rate": "💰"
}

INTERVAL_MAP = {
    "1 мин": "1", "3 мин": "3", "5 мин": "5",
    "15 мин": "15", "30 мин": "30", "1 час": "60"
}

INTERVAL_LABELS = {
    "1": "1 мин", "3": "3 мин", "5": "5 мин",
    "15": "15 мин", "30": "30 мин", "60": "1 час"
}


def configs_inline_keyboard(configs_data: list):
    """configs_data: список (id, name, screener_type)"""
    keyboard = []
    for cid, name, stype in configs_data:
        emoji = SCREENER_EMOJI.get(stype, "🔍")
        keyboard.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"load_{cid}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить конфиг", callback_data="delete_menu")])
    return InlineKeyboardMarkup(keyboard)


def delete_inline_keyboard(configs_data: list):
    keyboard = []
    for cid, name, stype in configs_data:
        keyboard.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"del_{cid}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_configs")])
    return InlineKeyboardMarkup(keyboard)