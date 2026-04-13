import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters
)
from config import BOT_TOKEN
from db.database import init_db
from bot.states import *
from bot.handlers import (
    start,
    auth_choose_handler,
    register_login_handler, register_password_handler,
    login_login_handler, login_password_handler,
    main_menu_handler,
    choose_screener_handler,
    price_spike_threshold_handler, price_spike_interval_handler,
    volume_multiplier_handler, volume_interval_handler,
    funding_threshold_handler,
    save_or_run_handler, save_config_name_handler,
    show_my_configs, my_configs_callback_handler,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TEXT = filters.TEXT & ~filters.COMMAND


def main():
    init_db()
    print("✅ База данных инициализирована")

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AUTH_CHOOSE: [
                MessageHandler(TEXT, auth_choose_handler),
            ],
            AUTH_REGISTER_LOGIN: [
                MessageHandler(TEXT, register_login_handler),
            ],
            AUTH_REGISTER_PASSWORD: [
                MessageHandler(TEXT, register_password_handler),
            ],
            AUTH_LOGIN_LOGIN: [
                MessageHandler(TEXT, login_login_handler),
            ],
            AUTH_LOGIN_PASSWORD: [
                MessageHandler(TEXT, login_password_handler),
            ],
            MAIN_MENU: [
                MessageHandler(TEXT, main_menu_handler),
            ],
            CHOOSE_SCREENER: [
                MessageHandler(TEXT, choose_screener_handler),
            ],
            PRICE_SPIKE_THRESHOLD: [
                MessageHandler(TEXT, price_spike_threshold_handler),
            ],
            PRICE_SPIKE_INTERVAL: [
                MessageHandler(TEXT, price_spike_interval_handler),
            ],
            VOLUME_MULTIPLIER: [
                MessageHandler(TEXT, volume_multiplier_handler),
            ],
            VOLUME_INTERVAL: [
                MessageHandler(TEXT, volume_interval_handler),
            ],
            FUNDING_THRESHOLD: [
                MessageHandler(TEXT, funding_threshold_handler),
            ],
            SAVE_OR_RUN: [
                MessageHandler(TEXT, save_or_run_handler),
            ],
            SAVE_CONFIG_NAME: [
                MessageHandler(TEXT, save_config_name_handler),
            ],
            MY_CONFIGS: [
                CallbackQueryHandler(my_configs_callback_handler),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv)
    print("🤖 Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()