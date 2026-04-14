import hashlib
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.keyboards import (
    auth_keyboard, main_menu_keyboard, screener_type_keyboard,
    interval_keyboard, save_or_run_keyboard, back_to_main_keyboard,
    configs_inline_keyboard, delete_inline_keyboard,
    INTERVAL_MAP, INTERVAL_LABELS
)
from bot.states import *
from db.database import get_db
from db.models import User, ScreenerConfig
from screeners.funding_rate import check_funding_rate
from screeners.price_spike import check_price_spike
from screeners.orderbook import check_orderbook_walls

logger = logging.getLogger(__name__)

active_jobs: dict = {}
temp_configs: dict = {}
auth_users: dict = {}

INTERVAL_TO_SECONDS = {
    "1": 60, "3": 180, "5": 300,
    "15": 900, "30": 1800, "60": 3600
}


# хэш пароля

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# бд — пользователи

def db_register_user(telegram_id: int, login: str, password: str, first_name: str):
    db = get_db()
    try:
        existing = db.query(User).filter(User.login == login).first()
        if existing:
            return None, "login_taken"
        user = User(
            telegram_id=telegram_id,
            login=login,
            password_hash=hash_password(password),
            first_name=first_name
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id, "ok"
    finally:
        db.close()


def db_login_user(login: str, password: str):
    db = get_db()
    try:
        user = db.query(User).filter(User.login == login).first()
        if not user:
            return None, "not_found"
        if user.password_hash != hash_password(password):
            return None, "wrong_password"
        return user.id, "ok"
    finally:
        db.close()


def db_get_configs(user_db_id: int):
    db = get_db()
    try:
        configs = db.query(ScreenerConfig).filter(ScreenerConfig.user_id == user_db_id).all()
        return [(c.id, c.name, c.screener_type, c.params) for c in configs]
    finally:
        db.close()


def db_save_config(user_db_id: int, name: str, params: dict):
    db = get_db()
    try:
        cfg = ScreenerConfig(
            user_id=user_db_id,
            name=name,
            screener_type=params.get("type", "unknown"),
            params=params
        )
        db.add(cfg)
        db.commit()
        return True
    finally:
        db.close()


def db_delete_config(config_id: int):
    db = get_db()
    try:
        cfg = db.query(ScreenerConfig).filter(ScreenerConfig.id == config_id).first()
        if cfg:
            db.delete(cfg)
            db.commit()
            return True
        return False
    finally:
        db.close()



def is_authed(telegram_id: int) -> bool:
    return telegram_id in auth_users


def remove_active_job(telegram_id: int):
    if telegram_id in active_jobs:
        try:
            active_jobs[telegram_id].schedule_removal()
        except Exception:
            pass
        del active_jobs[telegram_id]


# /start

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    if is_authed(tid):
        await update.message.reply_text(
            "👋 Ты уже вошёл в аккаунт.\n\nВыбери действие:",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    await update.message.reply_text(
        "👋 Добро пожаловать в *Crypto Screener Bot*!\n\n"
        "Бот отслеживает крипторынок на Bybit:\n"
        "• 📈 Резкие изменения цены\n"
        "• 📖 Крупные заявки в стакане\n"
        "• 💰 Экстремальные ставки фандинга\n\n"
        "Для начала нужно войти или зарегистрироваться:",
        reply_markup=auth_keyboard(),
        parse_mode="Markdown"
    )
    return AUTH_CHOOSE


# регистрация

async def auth_choose_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📝 Регистрация":
        await update.message.reply_text(
            "📝 *Регистрация*\n\nПридумай логин (только буквы и цифры, 3–30 символов):",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return AUTH_REGISTER_LOGIN

    elif text == "🔑 Войти":
        await update.message.reply_text(
            "🔑 *Вход*\n\nВведи свой логин:",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return AUTH_LOGIN_LOGIN

    else:
        await update.message.reply_text("Нажми одну из кнопок ниже 👇", reply_markup=auth_keyboard())
        return AUTH_CHOOSE


async def register_login_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    if not text.isalnum() or len(text) > 30 or len(text) < 3:
        await update.message.reply_text(
            "❌ Логин должен содержать только буквы и цифры, от 3 до 30 символов.\nПопробуй ещё раз:"
        )
        return AUTH_REGISTER_LOGIN

    context.user_data["reg_login"] = text
    await update.message.reply_text(
        f"✅ Логин: *{text}*\n\nТеперь придумай пароль (минимум 6 символов):",
        parse_mode="Markdown"
    )
    return AUTH_REGISTER_PASSWORD


async def register_password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()

    if password == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    if len(password) < 6:
        await update.message.reply_text("❌ Пароль должен быть минимум 6 символов. Попробуй ещё раз:")
        return AUTH_REGISTER_PASSWORD

    login = context.user_data.get("reg_login")
    tid = update.effective_user.id
    first_name = update.effective_user.first_name or ""

    user_id, status = db_register_user(tid, login, password, first_name)

    if status == "login_taken":
        await update.message.reply_text(
            f"❌ Логин *{login}* уже занят. Вернись назад и выбери другой.",
            reply_markup=auth_keyboard(),
            parse_mode="Markdown"
        )
        return AUTH_CHOOSE

    auth_users[tid] = user_id
    await update.message.reply_text(
        f"🎉 Регистрация успешна! Добро пожаловать, *{login}*!\n\nВыбери действие:",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU


# авторизация

async def login_login_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    context.user_data["login_input"] = text
    await update.message.reply_text("🔒 Введи пароль:")
    return AUTH_LOGIN_PASSWORD


async def login_password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()

    if password == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    login = context.user_data.get("login_input")
    tid = update.effective_user.id

    user_id, status = db_login_user(login, password)

    if status == "not_found":
        await update.message.reply_text(
            "❌ Логин не найден. Проверь правильность или зарегистрируйся.",
            reply_markup=auth_keyboard()
        )
        return AUTH_CHOOSE

    if status == "wrong_password":
        await update.message.reply_text("❌ Неверный пароль. Попробуй ещё раз:")
        return AUTH_LOGIN_PASSWORD

    auth_users[tid] = user_id
    await update.message.reply_text(
        f"✅ Вход выполнен! Добро пожаловать, *{login}*!\n\nВыбери действие:",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU


#  главное меню

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text

    if not is_authed(tid):
        await update.message.reply_text("⚠️ Сначала войди в аккаунт:", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    if text == "🔍 Запустить скринер":
        await update.message.reply_text(
            "🔍 *Выбери тип скринера:*\n\n"
            "📈 *Price Spike* — резкое изменение цены фьючерса\n"
            "📖 *Order Book Walls* — крупные заявки в спот стакане\n"
            "💰 *Funding Rate* — экстремальный фандинг фьючерсов",
            reply_markup=screener_type_keyboard(),
            parse_mode="Markdown"
        )
        return CHOOSE_SCREENER

    elif text == "📋 Мои конфиги":
        return await show_my_configs(update, context)

    elif text == "🛑 Остановить скринер":
        if tid in active_jobs:
            remove_active_job(tid)
            await update.message.reply_text(
                "🛑 Скринер остановлен. Уведомления больше не приходят.",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ Нет активного скринера.", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "ℹ️ *Справка*\n\n"
            "*📈 Price Spike* — мониторит фьючерсный рынок. Присылает сигнал когда цена "
            "резко меняется за выбранный интервал свечи.\n\n"
            "*📖 Order Book Walls* — мониторит спот стакан. Присылает сигнал когда "
            "находит крупную заявку рядом с текущей ценой. Ты сам задаёшь минимальный "
            "размер заявки в USDT и максимальное расстояние до неё в процентах.\n\n"
            "*💰 Funding Rate* — присылает сигнал когда ставка фандинга фьючерса "
            "превышает заданный порог. Высокий фандинг говорит о перегреве рынка.\n\n"
            "Конфиги сохраняются в базе данных и привязаны к твоему аккаунту.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU

    elif text == "🚪 Выйти из аккаунта":
        remove_active_job(tid)
        auth_users.pop(tid, None)
        temp_configs.pop(tid, None)
        await update.message.reply_text("🚪 Ты вышел из аккаунта.", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    else:
        await update.message.reply_text("Используй кнопки для навигации 👇", reply_markup=main_menu_keyboard())
        return MAIN_MENU


#выбор скринера

async def choose_screener_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    if text == "📈 Price Spike":
        temp_configs[tid] = {"type": "price_spike"}
        await update.message.reply_text(
            "📈 *Price Spike Screener*\n\n"
            "Введи минимальный процент изменения цены для сигнала.\n"
            "Например: `5` — сигнал при изменении на 5% и более за выбранный интервал.",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return PRICE_SPIKE_THRESHOLD

    elif text == "📖 Order Book Walls":
        temp_configs[tid] = {"type": "orderbook"}
        await update.message.reply_text(
            "📖 *Order Book Walls Screener*\n\n"
            "Введи минимальный размер заявки в USDT.\n"
            "Например: `500000` — искать заявки от 500 тысяч USDT и выше.",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return ORDERBOOK_MIN_SIZE

    elif text == "💰 Funding Rate":
        temp_configs[tid] = {"type": "funding_rate"}
        await update.message.reply_text(
            "💰 *Funding Rate Screener*\n\n"
            "Введи минимальную ставку фандинга для сигнала (в процентах).\n"
            "Например: `0.1` — сигнал при ставке ≥ 0.1%\n\n"
            "Обычно >0.1% считается высоким, <-0.05% — экстремально отрицательным.\n"
            "Скринер проверяет рынок каждые 5 минут.",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return FUNDING_THRESHOLD

    else:
        await update.message.reply_text("Выбери скринер с помощью кнопок 👇", reply_markup=screener_type_keyboard())
        return CHOOSE_SCREENER


# price spike

async def price_spike_threshold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    try:
        val = float(text.replace(",", "."))
        if val <= 0 or val > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи число от 1 до 100. Например: `5` или `3.5`", parse_mode="Markdown")
        return PRICE_SPIKE_THRESHOLD

    temp_configs[tid]["threshold"] = val
    await update.message.reply_text(
        f"✅ Порог: *{val}%*\n\nТеперь выбери интервал свечи:",
        reply_markup=interval_keyboard(),
        parse_mode="Markdown"
    )
    return PRICE_SPIKE_INTERVAL


async def price_spike_interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    interval = INTERVAL_MAP.get(text)
    if not interval:
        await update.message.reply_text("Выбери интервал с помощью кнопок 👇", reply_markup=interval_keyboard())
        return PRICE_SPIKE_INTERVAL

    temp_configs[tid]["interval"] = interval
    cfg = temp_configs[tid]

    await update.message.reply_text(
        f"📈 *Price Spike Screener*\n\n"
        f"Порог изменения: *{cfg['threshold']}%*\n"
        f"Интервал свечи: *{text}*\n\n"
        f"Что делаем?",
        reply_markup=save_or_run_keyboard(),
        parse_mode="Markdown"
    )
    return SAVE_OR_RUN


#order book walls

async def orderbook_min_size_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    try:
        # убираем пробелы на случай если пользователь написал "500 000"
        val = float(text.replace(" ", "").replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введи положительное число. Например: `500000` или `1000000`",
            parse_mode="Markdown"
        )
        return ORDERBOOK_MIN_SIZE

    temp_configs[tid]["min_size_usdt"] = val

    # форматируем красиво для отображения
    if val >= 1_000_000:
        size_label = f"{val / 1_000_000:.1f}M"
    else:
        size_label = f"{val / 1_000:.0f}K"

    await update.message.reply_text(
        f"✅ Минимальный размер заявки: *{size_label} USDT*\n\n"
        f"Теперь введи максимальное расстояние от текущей цены до заявки в процентах.\n"
        f"Например: `2` — искать заявки в пределах 2% от текущей цены.",
        reply_markup=back_to_main_keyboard(),
        parse_mode="Markdown"
    )
    return ORDERBOOK_DISTANCE


async def orderbook_distance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    try:
        val = float(text.replace(",", "."))
        if val <= 0 or val > 50:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введи число от 0.1 до 50. Например: `2` или `1.5`",
            parse_mode="Markdown"
        )
        return ORDERBOOK_DISTANCE

    temp_configs[tid]["max_distance_pct"] = val
    cfg = temp_configs[tid]

    min_usdt = cfg["min_size_usdt"]
    if min_usdt >= 1_000_000:
        size_label = f"{min_usdt / 1_000_000:.1f}M"
    else:
        size_label = f"{min_usdt / 1_000:.0f}K"

    await update.message.reply_text(
        f"📖 *Order Book Walls Screener*\n\n"
        f"Минимальный размер заявки: *{size_label} USDT*\n"
        f"Максимальное расстояние до заявки: *{val}%*\n"
        f"Проверка каждые 30 секунд\n\n"
        f"Что делаем?",
        reply_markup=save_or_run_keyboard(),
        parse_mode="Markdown"
    )
    return SAVE_OR_RUN


# funding rate

async def funding_threshold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    try:
        val = float(text.replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи положительное число. Например: `0.1`", parse_mode="Markdown")
        return FUNDING_THRESHOLD

    temp_configs[tid]["threshold"] = val / 100
    temp_configs[tid]["threshold_display"] = val

    await update.message.reply_text(
        f"💰 *Funding Rate Screener*\n\n"
        f"Минимальная ставка: *{val}%*\n"
        f"Проверка каждые 5 минут\n\n"
        f"Что делаем?",
        reply_markup=save_or_run_keyboard(),
        parse_mode="Markdown"
    )
    return SAVE_OR_RUN


#сохранение запуск

async def save_or_run_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    if text == "▶️ Запустить без сохранения":
        await update.message.reply_text("⏳ Запускаю скринер...", reply_markup=main_menu_keyboard())
        await launch_screener(tid, context, update.message.chat_id)
        await update.message.reply_text(
            "✅ Скринер запущен! Сигналы будут приходить в этот чат.\n"
            "Нажми *🛑 Остановить скринер* чтобы остановить.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU

    elif text == "💾 Сохранить и запустить":
        context.user_data["saving_config"] = True
        await update.message.reply_text(
            "💾 Введи название для этого конфига:\n"
            "Например: `BTC стакан 1M` или `Памп 5%`",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return SAVE_CONFIG_NAME

    else:
        await update.message.reply_text("Используй кнопки 👇", reply_markup=save_or_run_keyboard())
        return SAVE_OR_RUN


async def save_config_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text.strip()

    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    if not text or len(text) > 100:
        await update.message.reply_text("❌ Название должно быть от 1 до 100 символов.")
        return SAVE_CONFIG_NAME

    cfg = temp_configs.get(tid)
    user_db_id = auth_users.get(tid)

    if not cfg or not user_db_id:
        await update.message.reply_text("❌ Сессия истекла. Начни заново /start")
        return ConversationHandler.END

    db_save_config(user_db_id, text, cfg)
    await update.message.reply_text(f"✅ Конфиг *{text}* сохранён!", parse_mode="Markdown")
    await launch_screener(tid, context, update.message.chat_id)
    await update.message.reply_text(
        "▶️ Скринер запущен! Сигналы будут приходить в этот чат.\n"
        "Нажми *🛑 Остановить скринер* чтобы остановить.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU


#мои конфиги

async def show_my_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    user_db_id = auth_users.get(tid)

    if not user_db_id:
        await update.message.reply_text("⚠️ Сначала войди в аккаунт.", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    all_configs = db_get_configs(user_db_id)

    if not all_configs:
        await update.message.reply_text(
            "📋 У тебя нет сохранённых конфигов.\n\n"
            "Запусти скринер и выбери *💾 Сохранить и запустить*.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU

    short = [(cid, name, stype) for cid, name, stype, _ in all_configs]
    full = {cid: params for cid, _, _, params in all_configs}
    context.user_data["configs_short"] = short
    context.user_data["configs_full"] = full

    await update.message.reply_text(
        "📋 *Твои конфиги:*\n\nНажми на конфиг чтобы запустить скринер с этими настройками.",
        reply_markup=configs_inline_keyboard(short),
        parse_mode="Markdown"
    )
    return MY_CONFIGS


async def my_configs_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = update.effective_user.id
    data = query.data

    if data == "delete_menu":
        short = context.user_data.get("configs_short", [])
        await query.edit_message_text("🗑 Выбери конфиг для удаления:", reply_markup=delete_inline_keyboard(short))
        return MY_CONFIGS

    if data == "back_configs":
        short = context.user_data.get("configs_short", [])
        await query.edit_message_text(
            "📋 *Твои конфиги:*",
            reply_markup=configs_inline_keyboard(short),
            parse_mode="Markdown"
        )
        return MY_CONFIGS

    if data.startswith("del_"):
        config_id = int(data.replace("del_", ""))
        db_delete_config(config_id)
        await query.edit_message_text("✅ Конфиг удалён.")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Выбери действие:",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    if data.startswith("load_"):
        config_id = int(data.replace("load_", ""))
        full = context.user_data.get("configs_full", {})
        params = full.get(config_id)

        if not params:
            await query.edit_message_text("❌ Конфиг не найден.")
            return MAIN_MENU

        temp_configs[tid] = params
        await query.edit_message_text("✅ Конфиг загружен! Запускаю скринер...")
        await launch_screener(tid, context, query.message.chat_id)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="▶️ Скринер запущен! Сигналы будут приходить в этот чат.\n"
                 "Нажми *🛑 Остановить скринер* чтобы остановить.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU


#запуск скринера

async def launch_screener(telegram_id: int, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    remove_active_job(telegram_id)
    cfg = temp_configs.get(telegram_id, {})
    screener_type = cfg.get("type", "price_spike")

    if screener_type == "funding_rate":
        check_interval = 300        # каждые 5 минут
    elif screener_type == "orderbook":
        check_interval = 30         # каждые 30 секунд — стакан меняется быстро
    else:
        interval = cfg.get("interval", "5")
        check_interval = INTERVAL_TO_SECONDS.get(interval, 300)

    job = context.job_queue.run_repeating(
        screener_job,
        interval=check_interval,
        first=5,
        data={"telegram_id": telegram_id, "chat_id": chat_id, "config": cfg},
        name=f"screener_{telegram_id}"
    )
    active_jobs[telegram_id] = job


async def screener_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    cfg = job_data["config"]
    screener_type = cfg.get("type")

    try:
        if screener_type == "price_spike":
            interval = cfg.get("interval", "5")
            interval_label = INTERVAL_LABELS.get(interval, f"{interval} мин")
            alerts = check_price_spike(cfg.get("threshold", 5.0), interval)

            # каждый токен — отдельное сообщение
            for a in alerts[:5]:
                signal_line = "🟢 *PUMP*" if a["is_pump"] else "🔴 *DUMP*"
                text = (
                    f"{signal_line}\n"
                    f"*{a['pair']}*\n\n"
                    f"📊 Изменение: `{a['pct_change']:+.2f}%` за {interval_label}\n"
                    f"💰 Цена: `{a['price_from']}` → `{a['price_to']}`"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

        elif screener_type == "orderbook":
            alerts = check_orderbook_walls(
                min_size_usdt=cfg.get("min_size_usdt", 500_000),
                max_distance_pct=cfg.get("max_distance_pct", 2.0)
            )

            # каждая найденная заявка — отдельное сообщение
            for a in alerts[:5]:
                # bid — заявка на покупку снизу, ask — заявка на продажу сверху
                if a["side"] == "BID":
                    side_line = "🟩 *BID WALL* (поддержка)"
                else:
                    side_line = "🟥 *ASK WALL* (сопротивление)"

                # форматируем размер заявки
                usdt = a["size_usdt"]
                if usdt >= 1_000_000:
                    size_label = f"{usdt / 1_000_000:.2f}M"
                else:
                    size_label = f"{usdt / 1_000:.1f}K"

                text = (
                    f"{side_line}\n"
                    f"*{a['pair']}*\n\n"
                    f"💰 Текущая цена: `{a['current_price']}`\n"
                    f"🎯 Цена заявки: `{a['wall_price']}`\n"
                    f"📏 Расстояние: `{a['distance_pct']}%`\n"
                    f"📦 Размер заявки: `{size_label} USDT`"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

        elif screener_type == "funding_rate":
            alerts = check_funding_rate(cfg.get("threshold", 0.001))

            for a in alerts[:5]:
                text = (
                    f"💰 *FUNDING RATE ALERT*\n"
                    f"*{a['pair']}*\n\n"
                    f"📈 Ставка: `{a['funding_rate_pct']:+.4f}%`\n"
                    f"ℹ️ {a['direction']}"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"ошибка в screener_job: {e}")