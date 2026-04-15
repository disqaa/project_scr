import asyncio
import hashlib
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.keyboards import (
    auth_keyboard, main_menu_keyboard, screener_type_keyboard,
    interval_keyboard, save_or_run_keyboard, back_to_main_keyboard,
    configs_inline_keyboard, delete_inline_keyboard,
    manage_screeners_inline_keyboard,
    INTERVAL_MAP, INTERVAL_LABELS, SCREENER_NAMES, SCREENER_EMOJI
)
from bot.states import *
from db.database import get_db
from db.models import User, ScreenerConfig
from screeners.funding_rate import check_funding_rate
from screeners.price_spike import check_price_spike
from screeners.orderbook import fetch_orderbook_walls

logger = logging.getLogger(__name__)

active_jobs: dict = {}

temp_configs: dict = {}

auth_users: dict = {}

orderbook_known: dict = {}

INTERVAL_TO_SECONDS = {
    "1": 60, "3": 180, "5": 300,
    "15": 900, "30": 1800, "60": 3600
}


#хэш пароля

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


#бд — пользователи

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


#работа с активными скринерами

def is_authed(telegram_id: int) -> bool:
    return telegram_id in auth_users


def get_user_jobs(telegram_id: int) -> dict:
    return active_jobs.get(telegram_id, {})


def stop_one_screener(telegram_id: int, screener_type: str):
    jobs = active_jobs.get(telegram_id, {})
    if screener_type in jobs:
        try:
            jobs[screener_type].schedule_removal()
        except Exception:
            pass
        del jobs[screener_type]
        if not jobs:
            active_jobs.pop(telegram_id, None)
    if screener_type == "orderbook":
        orderbook_known.pop(telegram_id, None)


def stop_all_screeners(telegram_id: int):
    jobs = active_jobs.get(telegram_id, {})
    for job in jobs.values():
        try:
            job.schedule_removal()
        except Exception:
            pass
    active_jobs.pop(telegram_id, None)
    orderbook_known.pop(telegram_id, None)


def build_active_status_text(telegram_id: int) -> str:
    jobs = get_user_jobs(telegram_id)
    if not jobs:
        return "📊 *Активные скринеры*\n\nНет запущенных скринеров."
    lines = ["📊 *Активные скринеры:*\n"]
    for stype in jobs:
        emoji = SCREENER_EMOJI.get(stype, "🔍")
        name = SCREENER_NAMES.get(stype, stype)
        lines.append(f"✅ {emoji} {name}")
    return "\n".join(lines)


#/start

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
        "• 📈 Резкие изменения цены фьючерсов\n"
        "• 📖 Крупные заявки в спот стакане\n"
        "• 💰 Экстремальные ставки фандинга\n\n"
        "Можно запустить несколько скринеров одновременно.\n\n"
        "Для начала нужно войти или зарегистрироваться:",
        reply_markup=auth_keyboard(),
        parse_mode="Markdown"
    )
    return AUTH_CHOOSE


#регистрация

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


#авторизация

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


#главное меню

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
            "💰 *Funding Rate* — экстремальный фандинг фьючерсов\n\n"
            "Можно запустить несколько скринеров одновременно.",
            reply_markup=screener_type_keyboard(),
            parse_mode="Markdown"
        )
        return CHOOSE_SCREENER

    elif text == "📊 Активные скринеры":
        jobs = get_user_jobs(tid)
        status_text = build_active_status_text(tid)
        await update.message.reply_text(
            status_text,
            reply_markup=manage_screeners_inline_keyboard(jobs),
            parse_mode="Markdown"
        )
        return MANAGE_SCREENERS

    elif text == "📋 Мои конфиги":
        return await show_my_configs(update, context)

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "ℹ️ *Справка*\n\n"
            "*📈 Price Spike* — мониторит фьючерсный рынок. Сигнал когда цена "
            "резко меняется за выбранный интервал свечи.\n\n"
            "*📖 Order Book Walls* — мониторит спот стакан. При запуске присылает "
            "все крупные заявки в зоне. Потом присылает только новые заявки или "
            "вернувшиеся в зону после ухода цены.\n\n"
            "*💰 Funding Rate* — сигнал когда ставка фандинга фьючерса "
            "превышает заданный порог.\n\n"
            "Все скринеры работают одновременно. Управляй через *📊 Активные скринеры*.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU

    elif text == "🚪 Выйти из аккаунта":
        stop_all_screeners(tid)
        auth_users.pop(tid, None)
        temp_configs.pop(tid, None)
        await update.message.reply_text("🚪 Ты вышел из аккаунта.", reply_markup=auth_keyboard())
        return AUTH_CHOOSE

    else:
        await update.message.reply_text("Используй кнопки для навигации 👇", reply_markup=main_menu_keyboard())
        return MAIN_MENU


#управление активными скринерами

async def manage_screeners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = update.effective_user.id
    data = query.data

    if data == "noop":
        return MANAGE_SCREENERS

    if data == "close_manage":
        await query.delete_message()
        return MAIN_MENU

    if data == "stop_all":
        stop_all_screeners(tid)
        await query.edit_message_text(
            "🛑 *Все скринеры остановлены.*",
            reply_markup=manage_screeners_inline_keyboard({}),
            parse_mode="Markdown"
        )
        return MANAGE_SCREENERS

    if data.startswith("stop_"):
        screener_type = data.replace("stop_", "")
        stop_one_screener(tid, screener_type)
        emoji = SCREENER_EMOJI.get(screener_type, "")
        name = SCREENER_NAMES.get(screener_type, screener_type)
        jobs = get_user_jobs(tid)
        status_text = build_active_status_text(tid)
        await query.edit_message_text(
            f"🛑 {emoji} *{name}* остановлен.\n\n{status_text}",
            reply_markup=manage_screeners_inline_keyboard(jobs),
            parse_mode="Markdown"
        )
        return MANAGE_SCREENERS

    return MANAGE_SCREENERS


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
            "Обычно >0.1% считается высоким. Проверка каждые 5 минут.",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        return FUNDING_THRESHOLD

    else:
        await update.message.reply_text("Выбери скринер с помощью кнопок 👇", reply_markup=screener_type_keyboard())
        return CHOOSE_SCREENER


#пампы дампы

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
        await update.message.reply_text("❌ Введи число от 1 до 100. Например: `5`", parse_mode="Markdown")
        return PRICE_SPIKE_THRESHOLD
    temp_configs[tid]["threshold"] = val
    await update.message.reply_text(
        f"✅ Порог: *{val}%*\n\nВыбери интервал свечи:",
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


#заявки на споте

async def orderbook_min_size_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text.strip()
    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    try:
        val = float(text.replace(" ", "").replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи положительное число. Например: `500000`", parse_mode="Markdown")
        return ORDERBOOK_MIN_SIZE
    temp_configs[tid]["min_size_usdt"] = val
    size_label = f"{val / 1_000_000:.1f}M" if val >= 1_000_000 else f"{val / 1_000:.0f}K"
    await update.message.reply_text(
        f"✅ Минимальный размер заявки: *{size_label} USDT*\n\n"
        f"Введи максимальное расстояние от текущей цены до заявки в процентах.\n"
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
        await update.message.reply_text("❌ Введи число от 0.1 до 50. Например: `2`", parse_mode="Markdown")
        return ORDERBOOK_DISTANCE
    temp_configs[tid]["max_distance_pct"] = val
    cfg = temp_configs[tid]
    min_usdt = cfg["min_size_usdt"]
    size_label = f"{min_usdt / 1_000_000:.1f}M" if min_usdt >= 1_000_000 else f"{min_usdt / 1_000:.0f}K"
    await update.message.reply_text(
        f"📖 *Order Book Walls Screener*\n\n"
        f"Минимальный размер заявки: *{size_label} USDT*\n"
        f"Максимальное расстояние: *{val}%*\n"
        f"Проверка каждые 60 секунд\n\n"
        f"Что делаем?",
        reply_markup=save_or_run_keyboard(),
        parse_mode="Markdown"
    )
    return SAVE_OR_RUN


#funding rate

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


# cохранение / запуск

async def save_or_run_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    text = update.message.text
    if text == "◀️ Главное меню":
        await update.message.reply_text("Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    if text == "▶️ Запустить без сохранения":
        await launch_screener(tid, context, update.message.chat_id)
        stype = temp_configs.get(tid, {}).get("type", "")
        emoji = SCREENER_EMOJI.get(stype, "")
        name = SCREENER_NAMES.get(stype, "")
        await update.message.reply_text(
            f"✅ {emoji} *{name}* запущен!\n\n"
            f"Управляй скринерами через *📊 Активные скринеры*.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU
    elif text == "💾 Сохранить и запустить":
        await update.message.reply_text(
            "💾 Введи название для этого конфига:\nНапример: `BTC стакан 1M` или `Памп 5%`",
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
    stype = cfg.get("type", "")
    emoji = SCREENER_EMOJI.get(stype, "")
    name = SCREENER_NAMES.get(stype, "")
    await update.message.reply_text(
        f"▶️ {emoji} *{name}* запущен!\n\nУправляй скринерами через *📊 Активные скринеры*.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU


# мои конфиги

async def show_my_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    user_db_id = auth_users.get(tid)
    if not user_db_id:
        await update.message.reply_text("⚠️ Сначала войди в аккаунт.", reply_markup=auth_keyboard())
        return AUTH_CHOOSE
    # запрос в бд
    all_configs = await asyncio.to_thread(db_get_configs, user_db_id)
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
        await asyncio.to_thread(db_delete_config, config_id)
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
        await launch_screener(tid, context, query.message.chat_id)
        stype = params.get("type", "")
        emoji = SCREENER_EMOJI.get(stype, "")
        name = SCREENER_NAMES.get(stype, "")
        await query.edit_message_text(f"✅ Конфиг загружен!")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"▶️ {emoji} *{name}* запущен!\n\nУправляй скринерами через *📊 Активные скринеры*.",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return MAIN_MENU


#запуск скринера

async def launch_screener(telegram_id: int, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    cfg = temp_configs.get(telegram_id, {})
    screener_type = cfg.get("type", "price_spike")

    stop_one_screener(telegram_id, screener_type)

    if screener_type == "funding_rate":
        check_interval = 300
    elif screener_type == "orderbook":
        check_interval = 60
    else:
        interval = cfg.get("interval", "5")
        check_interval = INTERVAL_TO_SECONDS.get(interval, 300)

    job = context.job_queue.run_repeating(
        screener_job,
        interval=check_interval,
        first=5,
        data={"telegram_id": telegram_id, "chat_id": chat_id, "config": cfg},
        name=f"screener_{telegram_id}_{screener_type}"
    )

    if telegram_id not in active_jobs:
        active_jobs[telegram_id] = {}
    active_jobs[telegram_id][screener_type] = job


async def screener_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    cfg = job_data["config"]
    screener_type = cfg.get("type")
    tid = job_data["telegram_id"]

    try:
        #price spike
        if screener_type == "price_spike":
            interval = cfg.get("interval", "5")
            interval_label = INTERVAL_LABELS.get(interval, f"{interval} мин")

            alerts = await asyncio.to_thread(
                check_price_spike,
                cfg.get("threshold", 5.0),
                interval
            )

            for a in alerts[:5]:
                signal_line = "🟢 *PUMP*" if a["is_pump"] else "🔴 *DUMP*"
                text = (
                    f"📈 *PRICE SPIKE*\n"
                    f"{signal_line} — *{a['pair']}*\n\n"
                    f"📊 Изменение: `{a['pct_change']:+.2f}%` за {interval_label}\n"
                    f"💰 Цена: `{a['price_from']}` → `{a['price_to']}`"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

#order book walls
        elif screener_type == "orderbook":
            # запрос к бирже — в отдельном потоке
            current_walls = await asyncio.to_thread(
                fetch_orderbook_walls,
                cfg.get("min_size_usdt", 500_000),
                cfg.get("max_distance_pct", 2.0)
            )


            current_keys = set(current_walls.keys())
            known_keys = orderbook_known.get(tid, set())
            new_keys = current_keys - known_keys


            orderbook_known[tid] = current_keys

            # отправляем только новые стены
            for key in list(new_keys)[:5]:
                a = current_walls[key]
                side_line = "🟩 *BID WALL* (поддержка)" if a["side"] == "BID" else "🟥 *ASK WALL* (сопротивление)"
                usdt = a["size_usdt"]
                size_label = f"{usdt / 1_000_000:.2f}M" if usdt >= 1_000_000 else f"{usdt / 1_000:.1f}K"
                text = (
                    f"📖 *ORDER BOOK*\n"
                    f"{side_line} — *{a['pair']}*\n\n"
                    f"💰 Текущая цена: `{a['current_price']}`\n"
                    f"🎯 Цена заявки: `{a['wall_price']}`\n"
                    f"📏 Расстояние: `{a['distance_pct']}%`\n"
                    f"📦 Размер заявки: `{size_label} USDT`"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

# funding rate
        elif screener_type == "funding_rate":
            alerts = await asyncio.to_thread(
                check_funding_rate,
                cfg.get("threshold", 0.001)
            )

            for a in alerts[:5]:
                text = (
                    f"💰 *FUNDING RATE*\n"
                    f"*{a['pair']}*\n\n"
                    f"📈 Ставка: `{a['funding_rate_pct']:+.4f}%`\n"
                    f"ℹ️ {a['direction']}"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"ошибка в screener_job ({screener_type}): {e}")