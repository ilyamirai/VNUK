"""
Telegram бот для парсинга P2P ордербука
Пользователь выбирает фильтры через кнопки
"""
import sys
import io
import asyncio
import re
import json
import requests
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from wallet import Wallet

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Токен бота (получи у @BotFather)
BOT_TOKEN = "8209696618:AAHWQTYreuowaw71PnrNJXmba5jou4yiyr4"

# Глобальные настройки фильтров для каждого пользователя
user_filters = {}

# Глобальные настройки мониторинга для каждого пользователя
# Структура: {user_id: {'task': task, 'sbp': {state}, 'sberbank': {state}}}
# Один мониторинг проверяет оба банка и объединяет уведомления
user_monitors_usdt = {}
user_monitors_coins = {}

def get_funpay_usdt_rate(cookies=None):
    """Получить курс USDT TRC20 с FunPay"""
    try:
        from bs4 import BeautifulSoup

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
        }

        if cookies:
            headers['Cookie'] = cookies

        response = requests.get('https://funpay.com/account/balance', headers=headers, timeout=10)
        response.raise_for_status()

        # Ищем div.withdraw-box с data-data атрибутом
        soup = BeautifulSoup(response.text, 'html.parser')
        withdraw_box = soup.find('div', class_='withdraw-box')

        if not withdraw_box:
            print("withdraw-box не найден - возможно требуется авторизация")
            return None

        data_attr = withdraw_box.get('data-data')
        if not data_attr:
            print("data-data атрибут пустой")
            return None

        data = json.loads(data_attr)

        # Ищем курс USDT TRC20 в RUB
        if 'currencies' in data and 'rub' in data['currencies']:
            channels = data['currencies']['rub'].get('channels', [])
            for channel in channels:
                if channel.get('name') == 'USDT TRC20':
                    fee_info = channel.get('feeInfo', '')
                    # Ищем "курс 83.451"
                    rate_match = re.search(r'курс\s+([\d.]+)', fee_info)
                    if rate_match:
                        return float(rate_match.group(1))

        return None
    except Exception as e:
        print(f"Ошибка получения курса FunPay: {e}")
        return None

def get_default_filters():
    return {
        'base_currency': 'USDT',
        'quote_currency': 'RUB',
        'offer_type': 'PURCHASE',
        'merchant_verified': 'TRUSTED',  # Доверенные продавцы
        'payment_methods': None,
        'desired_amount': None,
        'limit': 5,
        'optimal': False  # Оптимальное предложение (онлайн + мин ≤30к)
    }

# Маппинг кодов банков в названия
PAYMENT_METHOD_CODES = {
    'sbp': 'sbp',
    'sberbankru': 'sberbankru'
}

PAYMENT_METHOD_NAMES = {
    'sbp': 'СБП',
    'sberbankru': 'Сбер'
}

def get_main_keyboard():
    """Главная клавиатура с кнопками"""
    keyboard = [
        [KeyboardButton("⚙️ Фильтры")],
        [KeyboardButton("📊 Парсинг"), KeyboardButton("🎯 Позиции Mirai")],
        [KeyboardButton("🔔 USDT"), KeyboardButton("🔔 COINS")],
        [KeyboardButton("🔕 Стоп мониторинг")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    user_filters[user_id] = get_default_filters()

    await update.message.reply_text(
        "🤖 P2P Ордербук Парсер\n\n"
        "Используй кнопки ниже для управления ботом:",
        reply_markup=get_main_keyboard()
    )

async def show_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие фильтры"""
    user_id = update.effective_user.id

    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    filters = user_filters[user_id]

    # Формируем текст с текущими настройками
    status = "⚙️ Текущие фильтры:\n\n"

    # Валюта
    status += f"💱 Валюта: {filters['base_currency']}/{filters['quote_currency']}\n"

    # Способ оплаты
    if filters['payment_methods']:
        if filters['payment_methods'] == ['sberbankru', 'sbp']:
            status += "💳 Оплата: Сбербанк + СБП\n"
        else:
            methods_map = {
                'sbp': 'СБП',
                'sberbankru': 'Сбербанк',
                'tinkoff': 'Тинькофф',
                'vtbbankru': 'ВТБ',
                'alfabank': 'Альфа-Банк'
            }
            method_name = methods_map.get(filters['payment_methods'][0], filters['payment_methods'][0])
            status += f"💳 Оплата: {method_name}\n"
    else:
        status += "💳 Оплата: Любой способ\n"

    # Объём
    if filters['desired_amount']:
        status += f"💰 Объём: {filters['desired_amount']:,} RUB\n"
    else:
        status += "💰 Объём: Любой\n"

    # Кастомные фильтры
    if filters['optimal']:
        status += "⭐ Оптимальное: Вкл (онлайн + мин ≤30к + автопринятие)\n"

    status += "\n📝 Выбери что изменить:"

    # Меню редактирования
    keyboard = [
        [InlineKeyboardButton("💱 Валюта", callback_data="filter_currency")],
        [InlineKeyboardButton("💳 Способ оплаты", callback_data="filter_payment")],
        [InlineKeyboardButton("💰 Объём сделки", callback_data="filter_amount")],
        [InlineKeyboardButton("⭐ Оптимальное предложение", callback_data="filter_optimal")],
        [InlineKeyboardButton("🔄 Сброс", callback_data="filter_reset")],
        [InlineKeyboardButton("✅ Готово", callback_data="filter_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            status,
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            status,
            reply_markup=reply_markup
        )

async def filter_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор валюты"""
    keyboard = [
        [InlineKeyboardButton("USDT/RUB", callback_data="curr_USDT_RUB")],
        [InlineKeyboardButton("BTC/RUB", callback_data="curr_BTC_RUB")],
        [InlineKeyboardButton("TON/RUB", callback_data="curr_TON_RUB")],
        [InlineKeyboardButton("ETH/RUB", callback_data="curr_ETH_RUB")],
        [InlineKeyboardButton("NOT/RUB", callback_data="curr_NOT_RUB")],
        [InlineKeyboardButton("« Назад", callback_data="back_filters")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "Выбери валютную пару:",
        reply_markup=reply_markup
    )

async def filter_verified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор уровня проверки"""
    keyboard = [
        [InlineKeyboardButton("✓ Только проверенные", callback_data="verified_VERIFIED")],
        [InlineKeyboardButton("⭐ Только доверенные", callback_data="verified_TRUSTED")],
        [InlineKeyboardButton("👥 Все продавцы", callback_data="verified_ALL")],
        [InlineKeyboardButton("« Назад", callback_data="back_filters")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "Уровень проверки продавца:",
        reply_markup=reply_markup
    )

async def filter_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор способа оплаты"""
    keyboard = [
        [InlineKeyboardButton("🏦💸 Сбербанк + СБП", callback_data="payment_sber_sbp")],
        [InlineKeyboardButton("💸 СБП", callback_data="payment_sbp")],
        [InlineKeyboardButton("🏦 Сбербанк", callback_data="payment_sberbankru")],
        [InlineKeyboardButton("🏦 Тинькофф", callback_data="payment_tinkoff")],
        [InlineKeyboardButton("🏦 ВТБ", callback_data="payment_vtbbankru")],
        [InlineKeyboardButton("🏦 Альфа-Банк", callback_data="payment_alfabank")],
        [InlineKeyboardButton("❌ Без фильтра", callback_data="payment_none")],
        [InlineKeyboardButton("« Назад", callback_data="back_filters")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "Способ оплаты:",
        reply_markup=reply_markup
    )

async def filter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор объёма сделки"""
    keyboard = [
        [InlineKeyboardButton("30,000 RUB", callback_data="amount_30000")],
        [InlineKeyboardButton("45,000 RUB", callback_data="amount_45000")],
        [InlineKeyboardButton("55,000 RUB", callback_data="amount_55000")],
        [InlineKeyboardButton("70,000 RUB", callback_data="amount_70000")],
        [InlineKeyboardButton("❌ Без фильтра", callback_data="amount_none")],
        [InlineKeyboardButton("« Назад", callback_data="back_filters")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "Выбери желаемый объём сделки:",
        reply_markup=reply_markup
    )

async def filter_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор количества результатов"""
    keyboard = [
        [InlineKeyboardButton("5", callback_data="limit_5"),
         InlineKeyboardButton("10", callback_data="limit_10")],
        [InlineKeyboardButton("20", callback_data="limit_20"),
         InlineKeyboardButton("50", callback_data="limit_50")],
        [InlineKeyboardButton("« Назад", callback_data="back_filters")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "Количество результатов:",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    data = query.data

    # Навигация
    if data == "back_filters":
        await show_filters(update, context)
        return
    elif data == "filter_currency":
        await filter_currency(update, context)
        return
    elif data == "filter_payment":
        await filter_payment(update, context)
        return
    elif data == "filter_amount":
        await filter_amount(update, context)
        return
    elif data == "filter_optimal":
        # Переключаем режим оптимального предложения
        user_filters[user_id]['optimal'] = not user_filters[user_id]['optimal']
        status = "Вкл ✅" if user_filters[user_id]['optimal'] else "Выкл ❌"
        await query.edit_message_text(f"⭐ Оптимальное предложение: {status}\n\n(Онлайн + минимум ≤30,000 RUB + автопринятие)")
        await show_filters(update, context)
        return
    elif data == "filter_reset":
        # Сброс всех фильтров к дефолтным
        user_filters[user_id] = get_default_filters()
        await query.edit_message_text("🔄 Фильтры сброшены к настройкам по умолчанию")
        await show_filters(update, context)
        return
    elif data == "filter_done":
        await query.edit_message_text("✅ Настройки сохранены!\n\nИспользуй /parse для получения данных\n\n⭐ Показываются только доверенные продавцы")
        return

    # Установка фильтров
    if data.startswith("curr_"):
        currencies = data.replace("curr_", "").split("_")
        user_filters[user_id]['base_currency'] = currencies[0]
        user_filters[user_id]['quote_currency'] = currencies[1]
        await query.edit_message_text(f"✓ Выбрано: {currencies[0]}/{currencies[1]}")
        await show_filters(update, context)

    elif data.startswith("verified_"):
        verified = data.replace("verified_", "")
        user_filters[user_id]['merchant_verified'] = None if verified == "ALL" else verified
        await query.edit_message_text(f"✓ Фильтр проверки установлен")
        await show_filters(update, context)

    elif data.startswith("payment_"):
        payment = data.replace("payment_", "")
        if payment == "none":
            user_filters[user_id]['payment_methods'] = None
        elif payment == "sber_sbp":
            # Сбербанк + СБП одновременно
            user_filters[user_id]['payment_methods'] = ['sberbankru', 'sbp']
        else:
            user_filters[user_id]['payment_methods'] = [payment]
        await query.edit_message_text(f"✓ Способ оплаты установлен")
        await show_filters(update, context)

    elif data.startswith("amount_"):
        amount_str = data.replace("amount_", "")
        if amount_str == "none":
            user_filters[user_id]['desired_amount'] = None
            await query.edit_message_text(f"✓ Объём сделки: без ограничений")
        else:
            amount = int(amount_str)
            user_filters[user_id]['desired_amount'] = amount
            await query.edit_message_text(f"✓ Объём сделки: {amount:,} RUB")
        await show_filters(update, context)

    elif data.startswith("limit_"):
        limit = int(data.replace("limit_", ""))
        user_filters[user_id]['limit'] = limit
        await query.edit_message_text(f"✓ Количество: {limit}")
        await show_filters(update, context)

async def parse_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Парсинг ордербука с текущими фильтрами"""
    user_id = update.effective_user.id

    # Получаем фильтры пользователя, НЕ сбрасываем
    filters = user_filters.get(user_id, get_default_filters())

    await update.message.reply_text("⏳ Загружаю данные...")

    try:
        # Подключаемся к API (токен загружается каждый раз заново для актуальности)
        w = Wallet.token_from_file('token.txt')

        # Получаем рыночную цену
        market_rate_data = w.get_p2p_rate(
            base=filters['base_currency'],
            quote=filters['quote_currency']
        )
        market_rate = float(market_rate_data['rate'])

        # Если включен фильтр "Оптимальное", не передаём desired_amount в API
        # так как фильтр сам проверяет лимит <= 30000
        api_desired_amount = None if filters['optimal'] else filters['desired_amount']

        # Получаем данные (запрашиваем больше, чтобы отфильтровать проверенных)
        offers = w.get_p2p_market(
            base_currency_code=filters['base_currency'],
            quote_currency_code=filters['quote_currency'],
            offer_type=filters['offer_type'],
            limit=50,  # Запрашиваем больше для фильтрации
            merchant_verified=filters['merchant_verified'],
            payment_method_codes=filters['payment_methods'],
            desired_amount=api_desired_amount  # Фильтр по объёму
        )

        if not offers:
            await update.message.reply_text("❌ Предложений не найдено")
            return

        # Фильтруем только объявления с временем оплаты 15 минут
        filtered_offers = []
        for offer in offers:
            unknown_things = getattr(offer, 'unknown_things', {})
            payment_timeout = unknown_things.get('paymentConfirmationTimeout', '')
            # PT15M = 15 минут в формате ISO 8601
            if payment_timeout == 'PT15M':
                filtered_offers.append(offer)
        offers = filtered_offers

        # Фильтр ОНЛАЙН (всегда применяется)
        online_offers = []
        for offer in offers:
            user = getattr(offer, 'user', None)
            online_status = getattr(user, 'onlineStatus', 'OFFLINE') if user else 'OFFLINE'
            if online_status == 'ONLINE':
                online_offers.append(offer)
        offers = online_offers

        if filters['optimal']:
            optimal_offers = []
            for offer in offers:
                min_amount = getattr(offer.orderAmountLimits, 'min', 999999)
                # Проверяем автопринятие
                unknown_things = getattr(offer, 'unknown_things', {})
                is_auto_accept = unknown_things.get('isAutoAccept', False)
                # Минимум <= 30000 + автопринятие
                if min_amount <= 30000 and is_auto_accept:
                    optimal_offers.append(offer)
            offers = optimal_offers

        if not offers:
            await update.message.reply_text("❌ Доверенных продавцов не найдено")
            return

        # Ищем продавца "Mirai" в результатах
        target_position = None
        target_data = None

        for i, offer in enumerate(offers, 1):
            user = getattr(offer, 'user', None)
            nickname = getattr(user, 'nickname', 'N/A') if user else 'N/A'
            if nickname.startswith('Mirai'):
                target_position = i
                target_data = {
                    'nickname': nickname,
                    'price': getattr(offer.price, 'value', 0),
                    'min_amount': getattr(offer.orderAmountLimits, 'min', 0),
                    'max_amount': getattr(offer.orderAmountLimits, 'max', 0),
                    'rating': getattr(getattr(user, 'statistics', None), 'successPercent', 0) if user else 0,
                    'orders': getattr(getattr(user, 'statistics', None), 'totalOrdersCount', 0) if user else 0
                }
                break

        # Формируем ответ
        type_emoji = "📈" if filters['offer_type'] == "PURCHASE" else "📉"
        response = f"{type_emoji} {filters['base_currency']}/{filters['quote_currency']}\n"

        # Показываем рыночную цену
        response += f"📊 Рыночная цена: {market_rate:.2f} {filters['quote_currency']}\n\n"

        # Показываем активные фильтры (если есть)
        active_filters = []
        if filters['payment_methods']:
            # Если это Сбербанк + СБП, показываем специальное название
            if set(filters['payment_methods']) == {'sberbankru', 'sbp'}:
                active_filters.append(f"• Оплата: Сбербанк + СБП")
            else:
                payment_names = {
                    'sbp': 'СБП',
                    'sberbankru': 'Сбербанк',
                    'tinkoff': 'Тинькофф',
                    'vtbbankru': 'ВТБ',
                    'alfabank': 'Альфа-Банк'
                }
                methods = [payment_names.get(m, m) for m in filters['payment_methods']]
                active_filters.append(f"• Оплата: {', '.join(methods)}")
        if filters['desired_amount']:
            active_filters.append(f"• Сумма: {filters['desired_amount']:,} RUB")
        if filters['optimal']:
            active_filters.append(f"• Оптимальное")
        if active_filters:
            response += "⚙️ Фильтры:\n"
            response += "\n".join(active_filters) + "\n\n"


        response += f"Найдено: {len(offers)} предложений\n\n"

        # Уведомление о Mirai
        if target_position:
            mirai_percent = (target_data['price'] / market_rate) * 100
            response += f"🎯 Mirai на {target_position} месте!\n"
            response += f"{target_data['price']:.2f} {filters['quote_currency']} ({mirai_percent:.2f}%) | {target_data['orders']} сделок | {target_data['rating']}%\n"
            response += f"Лимит: {target_data['min_amount']:.0f} - {target_data['max_amount']:.0f} {filters['quote_currency']}\n\n"
        else:
            response += f"⚠️ Mirai не найден в списке\n\n"

        response += "ТОП предложения:\n\n"

        for i, offer in enumerate(offers[:filters['limit']], 1):
            user = getattr(offer, 'user', None)
            stats = getattr(user, 'statistics', None) if user else None
            price = getattr(offer.price, 'value', 0)

            # Лимиты ордера
            min_amount = getattr(offer.orderAmountLimits, 'min', 0)
            max_amount = getattr(offer.orderAmountLimits, 'max', 0)

            nickname = getattr(user, 'nickname', 'N/A') if user else 'N/A'
            verified = '✓' if (user and getattr(user, 'isVerified', False)) else ''
            rating = getattr(stats, 'successPercent', 0) if stats else 0
            orders = getattr(stats, 'totalOrdersCount', 0) if stats else 0

            # Выделяем Mirai если он в топе
            if nickname.startswith('Mirai'):
                response += f"🎯 {i}. {nickname} {verified}\n"
            else:
                response += f"{i}. {nickname} {verified}\n"

            # Вычисляем процент от рыночной цены
            price_percent = (price / market_rate) * 100

            response += f"{price:.2f} {filters['quote_currency']} ({price_percent:.2f}%) | {orders} сделок | {rating}%\n"
            response += f"Лимит: {min_amount:.0f} - {max_amount:.0f} {filters['quote_currency']}\n"

            # Показываем TakerFilter если есть
            unknown_things = getattr(offer, 'unknown_things', {})
            taker_filter = unknown_things.get('takerFilter', {})
            if taker_filter:
                min_completed = taker_filter.get('minCompletedOrders', 0)
                min_percent = taker_filter.get('minSuccessPercent', 0)
                if min_completed > 0 or min_percent > 0:
                    response += f"⚠️ Требования: ≥{min_completed} сделок, ≥{min_percent}% успеха\n"

            response += "\n"

        await update.message.reply_text(response)

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие настройки"""
    user_id = update.effective_user.id

    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    filters = user_filters[user_id]

    status = "⚙️ Текущие настройки:\n\n"
    status += f"💱 Валюта: {filters['base_currency']}/{filters['quote_currency']}\n"

    # Оплата
    if filters['payment_methods']:
        if set(filters['payment_methods']) == {'sberbankru', 'sbp'}:
            status += f"💳 Оплата: Сбербанк + СБП\n"
        else:
            payment_names = {
                'sbp': 'СБП',
                'sberbankru': 'Сбербанк',
                'tinkoff': 'Тинькофф',
                'vtbbankru': 'ВТБ',
                'alfabank': 'Альфа-Банк'
            }
            methods = [payment_names.get(m, m) for m in filters['payment_methods']]
            status += f"💳 Оплата: {', '.join(methods)}\n"
    else:
        status += f"💳 Оплата: Любая\n"

    # Объём
    if filters['desired_amount']:
        status += f"Объём: {filters['desired_amount']:,} RUB\n"
    else:
        status += f"Объём: Любой\n"

    # Кастомные фильтры
    if filters['optimal']:
        status += f"⭐ Оптимальное: Вкл (онлайн + мин ≤30,000 RUB + автопринятие)\n"
    await update.message.reply_text(status)

def get_offers_for_bank(w, filters, payment_method):
    """
    Получает офферы для конкретного банка

    Returns:
        tuple: (offers, market_rate) или (None, None) при ошибке
    """
    try:
        # Получаем рыночную цену
        market_rate_data = w.get_p2p_rate(
            base=filters['base_currency'],
            quote=filters['quote_currency']
        )
        market_rate = float(market_rate_data['rate'])

        # Если включен фильтр "Оптимальное", не передаём desired_amount в API
        api_desired_amount = None if filters['optimal'] else filters['desired_amount']

        # Получаем данные для конкретного банка
        offers = w.get_p2p_market(
            base_currency_code=filters['base_currency'],
            quote_currency_code=filters['quote_currency'],
            offer_type=filters['offer_type'],
            limit=50,
            merchant_verified=filters['merchant_verified'],
            payment_method_codes=[payment_method],
            desired_amount=api_desired_amount
        )

        if not offers:
            return None, None

        # Фильтруем PT15M
        offers = [o for o in offers if getattr(o, 'unknown_things', {}).get('paymentConfirmationTimeout', '') == 'PT15M']

        # Фильтр ОНЛАЙН (всегда применяется)
        offers = [o for o in offers if getattr(getattr(o, 'user', None), 'onlineStatus', 'OFFLINE') == 'ONLINE']

        if filters['optimal']:
            # Фильтр оптимального предложения
            offers = [
                o for o in offers
                if getattr(o.orderAmountLimits, 'min', 999999) <= 30000
                and getattr(o, 'unknown_things', {}).get('isAutoAccept', False)
            ]

        return offers, market_rate

    except Exception as e:
        print(f"Ошибка получения офферов для {payment_method}: {e}")
        return None, None

def find_mirai_position(offers):
    """Находит позицию Mirai в списке офферов"""
    for i, offer in enumerate(offers, 1):
        user = getattr(offer, 'user', None)
        nickname = getattr(user, 'nickname', 'N/A') if user else 'N/A'
        if nickname.startswith('Mirai'):
            return i
    return None

async def monitor_usdt_dual_banks(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Мониторинг USDT с проверкой СБП и Сбера одновременно
    Объединяет одинаковые события в одно уведомление
    """
    while True:
        try:
            # Получаем СОХРАНЕННЫЕ фильтры из момента запуска мониторинга
            monitor_data = user_monitors_usdt.get(user_id, {})
            filters = monitor_data.get('filters', get_default_filters())

            # Подключаемся к API
            w = Wallet.token_from_file('token.txt')

            # Проверяем оба банка
            banks_data = {}
            for bank_code in ['sbp', 'sberbankru']:
                offers, market_rate = get_offers_for_bank(w, filters, bank_code)
                if offers is not None:
                    position = find_mirai_position(offers)
                    banks_data[bank_code] = {
                        'offers': offers,
                        'market_rate': market_rate,
                        'position': position
                    }

            if not banks_data:
                await asyncio.sleep(10)
                continue

            # Анализируем события для каждого банка
            events = {}  # {event_type: [list of banks with this event]}

            for bank_code, data in banks_data.items():
                position = data['position']
                offers = data['offers']
                market_rate = data['market_rate']

                # Получаем состояние для этого банка
                bank_state = monitor_data.get(bank_code, {
                    'last_position': None,
                    'notified': False,
                    'gap_notified': False
                })

                last_position = bank_state.get('last_position')
                notified = bank_state.get('notified', False)
                gap_notified = bank_state.get('gap_notified', False)

                if position is not None:
                    # Mirai найден
                    if position == 1:
                        # Возврат на 1 место
                        if notified and last_position and last_position > 1:
                            event_key = 'return_to_first'
                            if event_key not in events:
                                events[event_key] = {'banks': [], 'data': data}
                            events[event_key]['banks'].append(bank_code)

                        # Проверка разрыва
                        if len(offers) >= 2:
                            mirai_price = getattr(offers[0].price, 'value', 0)
                            second_price = getattr(offers[1].price, 'value', 0)
                            mirai_percent = (mirai_price / market_rate) * 100
                            second_percent = (second_price / market_rate) * 100
                            gap_percent = mirai_percent - second_percent

                            if gap_percent > 0.1 and not gap_notified:
                                event_key = 'gap_alert'  # Убираем процент из ключа - он постоянно меняется
                                if event_key not in events:
                                    events[event_key] = {'banks': [], 'data': {**data, 'gap_percent': gap_percent}}
                                events[event_key]['banks'].append(bank_code)
                            elif gap_percent <= 0.1:
                                # Сбрасываем флаг разрыва
                                bank_state['gap_notified'] = False

                        # Обновляем состояние
                        bank_state['notified'] = False
                        bank_state['last_position'] = 1

                    elif position > 1 and not notified:
                        # Упал с первого места
                        event_key = f'position_{position}'
                        if event_key not in events:
                            events[event_key] = {'banks': [], 'data': {**data, 'position': position}}
                        events[event_key]['banks'].append(bank_code)

                        # Обновляем состояние
                        bank_state['notified'] = True
                        bank_state['last_position'] = position
                        bank_state['gap_notified'] = False

                    else:
                        # Позиция изменилась но уже уведомляли
                        bank_state['last_position'] = position

                else:
                    # Mirai не найден
                    bank_state['last_position'] = None

                # Сохраняем состояние банка
                user_monitors_usdt[user_id][bank_code] = bank_state

            # Отправляем объединенные уведомления
            for event_key, event_info in events.items():
                banks = event_info['banks']
                data = event_info['data']

                # Формируем название банков
                bank_str = ', '.join([PAYMENT_METHOD_NAMES.get(b, b) for b in sorted(banks)])

                if event_key == 'return_to_first':
                    message = f"✅ {filters['base_currency']} ({bank_str}): Mirai вернулся на 1 место!"
                    await context.bot.send_message(chat_id=user_id, text=message)

                    # Сбрасываем gap_notified для банков которые вернулись
                    for bank_code in banks:
                        user_monitors_usdt[user_id][bank_code]['gap_notified'] = False

                elif event_key == 'gap_alert':
                    gap_percent = data['gap_percent']
                    message = f"📉 {filters['base_currency']} ({bank_str}): Можно спуститься ниже! Разрыв: {gap_percent:.2f}%\n\n"
                    message += f"📊 ТОП-3 {filters['base_currency']}:\n\n"

                    for i, offer in enumerate(data['offers'][:3], 1):
                        user_obj = getattr(offer, 'user', None)
                        nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                        price = getattr(offer.price, 'value', 0)
                        price_pct = (price / data['market_rate']) * 100

                        if nickname.startswith('Mirai'):
                            message += f"🎯 {i}. {nickname}\n"
                        else:
                            message += f"{i}. {nickname}\n"
                        message += f"{price:.2f} ({price_pct:.2f}%)\n\n"

                    await context.bot.send_message(chat_id=user_id, text=message)

                    # Устанавливаем gap_notified для банков
                    for bank_code in banks:
                        user_monitors_usdt[user_id][bank_code]['gap_notified'] = True

                elif event_key.startswith('position_'):
                    position = data['position']
                    message = f"{filters['base_currency']} ({bank_str}): Mirai на #{position} месте!\n\n"
                    message += f"📊 ТОП-5 {filters['base_currency']}:\n\n"

                    for i, offer in enumerate(data['offers'][:5], 1):
                        user_obj = getattr(offer, 'user', None)
                        nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                        price = getattr(offer.price, 'value', 0)
                        price_pct = (price / data['market_rate']) * 100

                        if nickname.startswith('Mirai'):
                            message += f"🎯 {i}. {nickname}\n"
                        else:
                            message += f"{i}. {nickname}\n"
                        message += f"{price:.2f} ({price_pct:.2f}%)\n\n"

                    await context.bot.send_message(chat_id=user_id, text=message)

        except Exception as e:
            print(f"Ошибка мониторинга USDT для пользователя {user_id}: {e}")

        # Ждем 10 секунд до следующей проверки
        await asyncio.sleep(10)

async def monitor_target_position(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Фоновая задача мониторинга позиции Rare Lemur"""
    while True:
        try:
            # Получаем СОХРАНЕННЫЕ фильтры из момента запуска мониторинга
            monitor_data = user_monitors_usdt.get(user_id, {})
            filters = monitor_data.get('filters', get_default_filters())

            # Подключаемся к API
            w = Wallet.token_from_file('token.txt')

            # Получаем рыночную цену
            market_rate_data = w.get_p2p_rate(
                base=filters['base_currency'],
                quote=filters['quote_currency']
            )
            market_rate = float(market_rate_data['rate'])

            # Если включен фильтр "Оптимальное", не передаём desired_amount в API
            api_desired_amount = None if filters['optimal'] else filters['desired_amount']

            # Получаем данные
            offers = w.get_p2p_market(
                base_currency_code=filters['base_currency'],
                quote_currency_code=filters['quote_currency'],
                offer_type=filters['offer_type'],
                limit=50,
                merchant_verified=filters['merchant_verified'],
                payment_method_codes=filters['payment_methods'],
                desired_amount=api_desired_amount
            )

            if not offers:
                await asyncio.sleep(10)
                continue

            # Фильтруем PT15M
            filtered_offers = []
            for offer in offers:
                unknown_things = getattr(offer, 'unknown_things', {})
                payment_timeout = unknown_things.get('paymentConfirmationTimeout', '')
                if payment_timeout == 'PT15M':
                    filtered_offers.append(offer)
            offers = filtered_offers

            # Фильтр ОНЛАЙН (всегда применяется)
            online_offers = []
            for offer in offers:
                user = getattr(offer, 'user', None)
                online_status = getattr(user, 'onlineStatus', 'OFFLINE') if user else 'OFFLINE'
                if online_status == 'ONLINE':
                    online_offers.append(offer)
            offers = online_offers

            if filters['optimal']:
                optimal_offers = []
                for offer in offers:
                    min_amount = getattr(offer.orderAmountLimits, 'min', 999999)

                    # Проверяем автопринятие
                    unknown_things = getattr(offer, 'unknown_things', {})
                    is_auto_accept = unknown_things.get('isAutoAccept', False)

                    if min_amount <= 30000 and is_auto_accept:
                        optimal_offers.append(offer)
                offers = optimal_offers

            # Ищем Mirai во ВСЕХ результатах
            target_position = None
            for i, offer in enumerate(offers, 1):
                user = getattr(offer, 'user', None)
                nickname = getattr(user, 'nickname', 'N/A') if user else 'N/A'
                if nickname.startswith('Mirai'):
                    target_position = i
                    break

            # Логика уведомлений
            monitor_data = user_monitors_usdt.get(user_id, {})
            last_position = monitor_data.get('last_position')
            notified = monitor_data.get('notified', False)
            gap_notified = monitor_data.get('gap_notified', False)

            if target_position is not None:
                # Mirai найден
                if target_position == 1:
                    # На 1 месте - если был уведомлен (был не на 1), отправляем уведомление о возврате
                    if notified and last_position and last_position > 1:
                        await context.bot.send_message(chat_id=user_id, text=f"✅ {filters['base_currency']}: Mirai вернулся на 1 место!")
                        # Сбрасываем флаг разрыва при возврате на 1 место, чтобы заново проверить
                        user_monitors_usdt[user_id]['gap_notified'] = False
                    # Сбрасываем флаг уведомления
                    user_monitors_usdt[user_id]['notified'] = False
                    user_monitors_usdt[user_id]['last_position'] = 1

                    # Проверяем разрыв со вторым местом
                    if len(offers) >= 2:
                        mirai_price = getattr(offers[0].price, 'value', 0)
                        second_price = getattr(offers[1].price, 'value', 0)
                        mirai_percent = (mirai_price / market_rate) * 100
                        second_percent = (second_price / market_rate) * 100
                        gap_percent = mirai_percent - second_percent

                        if gap_percent > 0.1 and not gap_notified:
                            # Разрыв больше 0.1% - отправляем уведомление
                            message = f"📉 {filters['base_currency']}: Можно спуститься ниже! Разрыв: {gap_percent:.2f}%\n\n"
                            message += f"📊 ТОП-3 {filters['base_currency']}:\n\n"

                            for i, offer in enumerate(offers[:3], 1):
                                user_obj = getattr(offer, 'user', None)
                                nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                                price = getattr(offer.price, 'value', 0)
                                price_pct = (price / market_rate) * 100

                                if nickname.startswith('Mirai'):
                                    message += f"🎯 {i}. {nickname}\n"
                                else:
                                    message += f"{i}. {nickname}\n"
                                message += f"{price:.2f} ({price_pct:.2f}%)\n\n"

                            await context.bot.send_message(chat_id=user_id, text=message)
                            user_monitors_usdt[user_id]['gap_notified'] = True
                        elif gap_percent <= 0.1:
                            # Разрыв нормальный - сбрасываем флаг
                            user_monitors_usdt[user_id]['gap_notified'] = False
                elif target_position > 1 and not notified:
                    # НЕ на 1 месте и еще не уведомляли - отправляем уведомление
                    price_obj = getattr(offers[target_position-1].price, 'value', 0)
                    price_percent = (price_obj / market_rate) * 100

                    # Объединяем уведомление и ТОП-5 в одно сообщение
                    message = f"{filters['base_currency']}: Mirai на #{target_position} месте!\n\n"
                    message += f"📊 ТОП-5 {filters['base_currency']}:\n\n"

                    for i, offer in enumerate(offers[:5], 1):
                        user_obj = getattr(offer, 'user', None)
                        nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                        price = getattr(offer.price, 'value', 0)
                        price_pct = (price / market_rate) * 100

                        if nickname.startswith('Mirai'):
                            message += f"🎯 {i}. {nickname}\n"
                        else:
                            message += f"{i}. {nickname}\n"
                        message += f"{price:.2f} ({price_pct:.2f}%)\n\n"

                    await context.bot.send_message(chat_id=user_id, text=message)

                    user_monitors_usdt[user_id]['notified'] = True
                    user_monitors_usdt[user_id]['last_position'] = target_position
                    # Сбрасываем флаг разрыва, когда упали с 1 места
                    user_monitors_usdt[user_id]['gap_notified'] = False
                else:
                    # Позиция изменилась но уже уведомляли
                    user_monitors_usdt[user_id]['last_position'] = target_position
            else:
                # Mirai не найден
                user_monitors_usdt[user_id]['last_position'] = None

        except Exception as e:
            print(f"Ошибка мониторинга для пользователя {user_id}: {e}")

        # Ждем 10 секунд до следующей проверки
        await asyncio.sleep(10)

async def start_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск мониторинга позиции Rare Lemur"""
    user_id = update.effective_user.id

    # Проверяем что фильтры настроены
    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    # Проверяем не запущен ли уже мониторинг USDT
    if user_id in user_monitors_usdt and user_monitors_usdt[user_id].get('task'):
        await update.message.reply_text("🔔 Мониторинг USDT уже запущен!\n\nИспользуй 🔕 Стоп мониторинг для остановки")
        return

    # Сохраняем КОПИЮ текущих фильтров для мониторинга
    saved_filters = user_filters[user_id].copy()

    # Создаем задачу мониторинга
    task = asyncio.create_task(monitor_target_position(context, user_id))

    user_monitors_usdt[user_id] = {
        'task': task,
        'filters': saved_filters,  # Сохраняем копию фильтров
        'last_position': None,
        'notified': False,
        'gap_notified': False  # Флаг для уведомления о большом разрыве
    }

    # Выполняем первую проверку сразу
    try:
        w = Wallet.token_from_file('token.txt')

        market_rate_data = w.get_p2p_rate(
            base=saved_filters['base_currency'],
            quote=saved_filters['quote_currency']
        )
        market_rate = float(market_rate_data['rate'])

        # Если включен фильтр "Оптимальное", не передаём desired_amount в API
        api_desired_amount = None if saved_filters['optimal'] else saved_filters['desired_amount']

        offers = w.get_p2p_market(
            base_currency_code=saved_filters['base_currency'],
            quote_currency_code=saved_filters['quote_currency'],
            offer_type=saved_filters['offer_type'],
            limit=50,
            merchant_verified=saved_filters['merchant_verified'],
            payment_method_codes=saved_filters['payment_methods'],
            desired_amount=api_desired_amount
        )

        # Фильтруем PT15M
        filtered_offers = []
        for offer in offers:
            unknown_things = getattr(offer, 'unknown_things', {})
            payment_timeout = unknown_things.get('paymentConfirmationTimeout', '')
            if payment_timeout == 'PT15M':
                filtered_offers.append(offer)
        offers = filtered_offers

        # Фильтр ОНЛАЙН (всегда применяется)
        online_offers = []
        for offer in offers:
            user_obj = getattr(offer, 'user', None)
            online_status = getattr(user_obj, 'onlineStatus', 'OFFLINE') if user_obj else 'OFFLINE'
            if online_status == 'ONLINE':
                online_offers.append(offer)
        offers = online_offers

        if saved_filters['optimal']:
            optimal_offers = []
            for offer in offers:
                min_amount = getattr(offer.orderAmountLimits, 'min', 999999)

                # Проверяем автопринятие
                unknown_things = getattr(offer, 'unknown_things', {})
                is_auto_accept = unknown_things.get('isAutoAccept', False)

                if min_amount <= 30000 and is_auto_accept:
                    optimal_offers.append(offer)
            offers = optimal_offers

        # Ищем Mirai
        target_position = None
        target_price = None
        for i, offer in enumerate(offers, 1):
            user_obj = getattr(offer, 'user', None)
            nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
            if nickname.startswith('Mirai'):
                target_position = i
                target_price = getattr(offer.price, 'value', 0)
                break

        response = "🔔 Мониторинг позиции Mirai запущен!\n\n"

        # Показываем результат первой проверки
        if target_position is not None:
            price_percent = (target_price / market_rate) * 100
            if target_position == 1:
                response += f"✅ Mirai на 1 месте!\n"
            else:
                response += f"Mirai на {target_position} месте\n"
            response += f"Цена: {target_price:.2f} ({price_percent:.2f}%)\n\n"
        else:
            response += f"❌ Mirai не найден в стакане\n\n"

        response += "⚙️ Сохраненные фильтры:\n"
        response += f"• Валюта: {saved_filters['base_currency']}/{saved_filters['quote_currency']}\n"
        if saved_filters['payment_methods']:
            if set(saved_filters['payment_methods']) == {'sberbankru', 'sbp'}:
                response += f"• Оплата: Сбербанк + СБП\n"
            else:
                response += f"• Оплата: {', '.join(saved_filters['payment_methods'])}\n"
        if saved_filters['desired_amount']:
            response += f"• Сумма: {saved_filters['desired_amount']:,} RUB\n"
        if saved_filters['optimal']:
            response += f"• Оптимальное: Вкл\n"

    except Exception as e:
        response = f"🔔 Мониторинг запущен, но первая проверка не удалась:\n{str(e)}\n\n"

    await update.message.reply_text(response)

async def stop_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановка мониторинга"""
    user_id = update.effective_user.id

    stopped_monitors = []

    # Проверяем и останавливаем USDT мониторинг
    if user_id in user_monitors_usdt and user_monitors_usdt[user_id].get('task'):
        task = user_monitors_usdt[user_id]['task']
        task.cancel()
        del user_monitors_usdt[user_id]
        stopped_monitors.append('USDT')

    # Проверяем и останавливаем COINS мониторинг
    if user_id in user_monitors_coins and user_monitors_coins[user_id].get('task'):
        task = user_monitors_coins[user_id]['task']
        task.cancel()
        del user_monitors_coins[user_id]
        stopped_monitors.append('COINS')

    if stopped_monitors:
        await update.message.reply_text(f"🔕 Мониторинг остановлен: {', '.join(stopped_monitors)}")
    else:
        await update.message.reply_text("❌ Мониторинг не запущен")

def process_coin_position(coin, filters, sell_rate=None, usdt_market_rate=None):
    """Обработка позиции для одной монеты (для параллельного выполнения)"""
    try:
        wallet = Wallet.token_from_file('token.txt')

        # Получаем офферы с учётом ВСЕХ фильтров пользователя
        offers = wallet.get_p2p_market(
            base_currency_code=coin,
            quote_currency_code=filters['quote_currency'],
            offer_type=filters['offer_type'],
            merchant_verified=filters['merchant_verified'],
            payment_method_codes=filters['payment_methods'],
            desired_amount=filters['desired_amount'],
            limit=50
        )

        # Сначала фильтруем только онлайн + время оплаты ≤30 мин (всегда)
        filtered_offers = []
        for offer in offers:
            user = getattr(offer, 'user', None)
            online_status = getattr(user, 'onlineStatus', 'OFFLINE') if user else 'OFFLINE'

            # Проверяем время на оплату (формат ISO 8601: PT15M, PT30M)
            unknown_things = getattr(offer, 'unknown_things', {})
            payment_timeout = unknown_things.get('paymentConfirmationTimeout', '')
            # PT15M = 15 минут, PT30M = 30 минут
            allowed_timeouts = ['PT15M', 'PT30M']

            if online_status == 'ONLINE' and payment_timeout in allowed_timeouts:
                filtered_offers.append(offer)
        offers = filtered_offers

        if filters['optimal']:
            optimal_offers = []
            for offer in offers:
                min_amount = getattr(offer.orderAmountLimits, 'min', 999999)

                # Проверяем автопринятие
                unknown_things = getattr(offer, 'unknown_things', {})
                is_auto_accept = unknown_things.get('isAutoAccept', False)

                if min_amount <= 30000 and is_auto_accept:
                    optimal_offers.append(offer)
            offers = optimal_offers

        # Ищем Mirai
        position = None
        price = None

        for i, offer in enumerate(offers, 1):
            user = getattr(offer, 'user', None)
            nickname = getattr(user, 'nickname', '') if user else ''
            if nickname.startswith('Mirai'):
                position = i
                price = getattr(offer.price, 'value', 0)
                break

        if position:
            # Пересчитываем курс в USDT и спред с FunPay
            if coin != 'USDT':
                try:
                    # Получаем рыночный курс монеты к RUB
                    coin_rub_data = wallet.get_p2p_rate(base=coin, quote='RUB')
                    coin_rub_market = float(coin_rub_data['rate'])

                    # Получаем рыночный курс USDT к RUB
                    usdt_rub_data = wallet.get_p2p_rate(base='USDT', quote='RUB')
                    usdt_rub_market = float(usdt_rub_data['rate'])

                    # Сколько рублей получится за 1 USDT по курсу этого оффера
                    rub_per_usdt = (price / coin_rub_market) * usdt_rub_market

                    # Рассчитываем спред с FunPay и процент от рынка
                    price_vs_market = (price / coin_rub_market) * 100

                    # Для BTC добавляем 0.9% за свап к курсу
                    if coin == 'BTC':
                        rub_per_usdt_display = rub_per_usdt * 1.009
                    else:
                        rub_per_usdt_display = rub_per_usdt

                    if sell_rate:
                        spread_percent = ((rub_per_usdt_display - sell_rate) / sell_rate) * 100
                        return f"💎 {coin} • #{position}\n   Цена: {price_vs_market:.2f}% от рынка\n   1 USDT = {rub_per_usdt_display:.2f} ₽\n   Спред: {spread_percent:+.2f}%\n\n"
                    else:
                        return f"💎 {coin} • #{position}\n   Цена: {price_vs_market:.2f}% от рынка\n   1 USDT = {rub_per_usdt_display:.2f} ₽\n\n"
                except Exception as e:
                    # Если не удалось получить рыночную цену, показываем просто цену
                    return f"💎 {coin} • #{position}\n   Цена: {price:.2f} ₽\n\n"
            else:
                # Для USDT показываем процент от рынка, курс и спред
                if sell_rate and price > 0 and usdt_market_rate:
                    price_vs_market = (price / usdt_market_rate) * 100
                    spread_percent = ((price - sell_rate) / sell_rate) * 100
                    return f"💎 {coin} • #{position}\n   Цена: {price_vs_market:.2f}% от рынка\n   1 USDT = {price:.2f} ₽\n   Спред: {spread_percent:+.2f}%\n\n"
                else:
                    return f"💎 {coin} • #{position}\n   Цена: {price:.2f} ₽\n\n"
        else:
            return f"💎 {coin} • не найден\n\n"

    except Exception as e:
        return f"{coin}: ошибка ({str(e)[:30]}...)\n"

async def check_mirai_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить позиции Mirai по всем монетам с фильтрами"""
    user_id = update.effective_user.id

    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    filters = user_filters[user_id]
    coins = ['USDT', 'TON', 'BTC', 'ETH', 'NOT']
    response = "🎯 Позиции Mirai\n\n"

    # Получаем курс FunPay и рыночный курс USDT
    try:
        with open('funpay_cookies.txt', 'r', encoding='utf-8') as f:
            funpay_cookies = f.read().strip()
        funpay_rate = get_funpay_usdt_rate(cookies=funpay_cookies)

        # Получаем рыночный курс USDT
        wallet_temp = Wallet.token_from_file('token.txt')
        usdt_market_data = wallet_temp.get_p2p_rate(base='USDT', quote='RUB')
        usdt_market_rate = float(usdt_market_data['rate'])

        if funpay_rate:
            sell_rate = funpay_rate * 1.02  # +2% для продажи
            market_spread = ((funpay_rate - usdt_market_rate) / usdt_market_rate) * 100
            response += f"💵 FunPay: {funpay_rate:.3f} ₽\n"
            response += f"📊 Рынок:  {usdt_market_rate:.3f} ₽ ({market_spread:+.2f}%)\n\n"
        else:
            sell_rate = None
            response += "⚠️ Не удалось получить курс FunPay\n\n"
    except Exception as e:
        print(f"Ошибка получения курса FunPay: {e}")
        sell_rate = None
        usdt_market_rate = None
        response += "⚠️ Не удалось получить курс FunPay\n\n"

    try:
        # Используем ThreadPoolExecutor для параллельного выполнения запросов
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                loop.run_in_executor(executor, process_coin_position, coin, filters, sell_rate, usdt_market_rate)
                for coin in coins
            ]
            results = await asyncio.gather(*futures)

        # Добавляем результаты в правильном порядке
        for result in results:
            response += result

        await update.message.reply_text(response)

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def start_monitor_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мониторинг USDT с проверкой СБП и Сбера одновременно"""
    user_id = update.effective_user.id

    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    # Устанавливаем базовую валюту на USDT
    user_filters[user_id]['base_currency'] = 'USDT'

    # Проверяем не запущен ли уже мониторинг USDT
    if user_id in user_monitors_usdt and user_monitors_usdt[user_id].get('task'):
        await update.message.reply_text("🔔 Мониторинг USDT уже запущен!\n\nИспользуй 🔕 Стоп мониторинг для остановки")
        return

    # Сохраняем КОПИЮ текущих фильтров для мониторинга
    saved_filters = user_filters[user_id].copy()

    # Первая проверка - показываем текущие позиции
    try:
        w = Wallet.token_from_file('token.txt')

        initial_response = "🔔 Мониторинг USDT запущен!\n\n💳 Отслеживаемые банки: СБП, Сбер\n\n"

        for bank_code in ['sbp', 'sberbankru']:
            bank_name = PAYMENT_METHOD_NAMES.get(bank_code, bank_code)
            offers, market_rate = get_offers_for_bank(w, saved_filters, bank_code)

            if offers:
                position = find_mirai_position(offers)
                if position:
                    price = getattr(offers[position-1].price, 'value', 0)
                    price_percent = (price / market_rate) * 100
                    initial_response += f"🏦 {bank_name}: Mirai на #{position} месте\nЦена: {price:.2f} ({price_percent:.2f}%)\n\n"
                else:
                    initial_response += f"🏦 {bank_name}: Mirai не найден\n\n"

                # Показываем ТОП-5
                initial_response += f"📊 ТОП-5 {bank_name}:\n\n"
                for i, offer in enumerate(offers[:5], 1):
                    user_obj = getattr(offer, 'user', None)
                    nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                    price = getattr(offer.price, 'value', 0)
                    price_pct = (price / market_rate) * 100

                    if nickname.startswith('Mirai'):
                        initial_response += f"🎯 {i}. {nickname}\n"
                    else:
                        initial_response += f"{i}. {nickname}\n"
                    initial_response += f"{price:.2f} ({price_pct:.2f}%)\n\n"

                initial_response += "\n"
            else:
                initial_response += f"🏦 {bank_name}: Нет офферов\n\n"

        initial_response += "Одинаковые события будут объединяться в одно уведомление."
        await update.message.reply_text(initial_response)

    except Exception as e:
        await update.message.reply_text(f"🔔 Мониторинг USDT запущен!\n\n❌ Ошибка первой проверки: {str(e)}")

    # Создаем задачу мониторинга
    task = asyncio.create_task(monitor_usdt_dual_banks(context, user_id))

    # Инициализируем состояние для обоих банков
    user_monitors_usdt[user_id] = {
        'task': task,
        'filters': saved_filters,
        'sbp': {
            'last_position': None,
            'notified': False,
            'gap_notified': False
        },
        'sberbankru': {
            'last_position': None,
            'notified': False,
            'gap_notified': False
        }
    }

async def start_monitor_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мониторинг всех монет кроме USDT"""
    user_id = update.effective_user.id

    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()

    # Проверяем не запущен ли уже мониторинг COINS
    if user_id in user_monitors_coins and user_monitors_coins[user_id].get('task'):
        await update.message.reply_text("🔔 Мониторинг COINS уже запущен!\n\nИспользуй 🔕 Стоп мониторинг для остановки")
        return

    saved_filters = user_filters[user_id].copy()
    coins = ['TON', 'BTC', 'ETH', 'NOT']

    # Словарь для отслеживания уведомлений по каждой монете
    coins_state = {coin: {'last_position': None, 'notified': False, 'gap_notified': False} for coin in coins}

    # Первая проверка - показываем текущие позиции
    filter_status = []
    if saved_filters['optimal']:
        filter_status.append("• Оптимальное")

    if saved_filters['merchant_verified']:
        filter_status.append("• Верифицированные")

    if saved_filters['desired_amount']:
        filter_status.append(f"• Сумма: {saved_filters['desired_amount']:,} {saved_filters['quote_currency']}")

    if saved_filters['payment_methods']:
        payment_names = {
            'tinkoff': 'Тинькофф',
            'sberbank': 'Сбербанк',
            'raiffeisenbank': 'Райффайзен',
            'alfabank': 'Альфа-Банк'
        }
        methods = [payment_names.get(m, m) for m in saved_filters['payment_methods']]
        filter_status.append(f"• Оплата: {', '.join(methods)}")

    initial_response = "🔔 Мониторинг запущен для: TON, BTC, ETH, NOT\n\n"
    if filter_status:
        initial_response += "⚙️ Фильтры:\n" + "\n".join(filter_status) + "\n\n"
    for coin in coins:
        try:
            w = Wallet.token_from_file('token.txt')
            market_rate_data = w.get_p2p_rate(base=coin, quote=saved_filters['quote_currency'])
            market_rate = float(market_rate_data['rate'])

            # Если включен фильтр "Оптимальное", не передаём desired_amount в API
            # так как фильтр сам проверяет лимит <= 30000
            api_desired_amount = None if saved_filters['optimal'] else saved_filters['desired_amount']

            offers = w.get_p2p_market(
                base_currency_code=coin,
                quote_currency_code=saved_filters['quote_currency'],
                offer_type=saved_filters['offer_type'],
                limit=50,
                merchant_verified=saved_filters['merchant_verified'],
                payment_method_codes=saved_filters['payment_methods'],
                desired_amount=api_desired_amount
            )

            # Применяем фильтры
            filtered_offers = []
            for offer in offers:
                user_obj = getattr(offer, 'user', None)
                online_status = getattr(user_obj, 'onlineStatus', 'OFFLINE') if user_obj else 'OFFLINE'
                unknown_things = getattr(offer, 'unknown_things', {})
                payment_timeout = unknown_things.get('paymentConfirmationTimeout', '')
                if online_status == 'ONLINE' and payment_timeout == 'PT15M':
                    filtered_offers.append(offer)
            offers = filtered_offers

            if saved_filters['optimal']:
                offers = [o for o in offers if getattr(o.orderAmountLimits, 'min', 999999) <= 30000 and getattr(o, 'unknown_things', {}).get('isAutoAccept', False)]

            # Ищем Mirai
            position = None
            price = None
            for i, offer in enumerate(offers, 1):
                user_obj = getattr(offer, 'user', None)
                if getattr(user_obj, 'nickname', '').startswith('Mirai'):
                    position = i
                    price = getattr(offer.price, 'value', 0)
                    coins_state[coin]['last_position'] = i
                    break

            if position:
                price_percent = (price / market_rate) * 100
                initial_response += f"{coin}: Mirai на #{position} месте\nЦена: {price:.2f} ({price_percent:.2f}%)\n\n"
            else:
                initial_response += f"{coin}: Mirai не найден\n\n"

        except Exception as e:
            initial_response += f"{coin}: ошибка ({str(e)[:20]}...)\n\n"

    await update.message.reply_text(initial_response)

    # Создаем задачу для мониторинга
    async def monitor_multiple_coins():
        while True:
            for coin in coins:
                try:
                    w = Wallet.token_from_file('token.txt')
                    market_rate_data = w.get_p2p_rate(base=coin, quote=saved_filters['quote_currency'])
                    market_rate = float(market_rate_data['rate'])

                    # Если включен фильтр "Оптимальное", не передаём desired_amount в API
                    api_desired_amount = None if saved_filters['optimal'] else saved_filters['desired_amount']

                    offers = w.get_p2p_market(
                        base_currency_code=coin,
                        quote_currency_code=saved_filters['quote_currency'],
                        offer_type=saved_filters['offer_type'],
                        limit=50,
                        merchant_verified=saved_filters['merchant_verified'],
                        payment_method_codes=saved_filters['payment_methods'],
                        desired_amount=api_desired_amount
                    )

                    # Применяем фильтры
                    filtered_offers = []
                    for offer in offers:
                        user_obj = getattr(offer, 'user', None)
                        online_status = getattr(user_obj, 'onlineStatus', 'OFFLINE') if user_obj else 'OFFLINE'
                        unknown_things = getattr(offer, 'unknown_things', {})
                        payment_timeout = unknown_things.get('paymentConfirmationTimeout', '')
                        if online_status == 'ONLINE' and payment_timeout == 'PT15M':
                            filtered_offers.append(offer)
                    offers = filtered_offers

                    if saved_filters['optimal']:
                        offers = [o for o in offers if getattr(o.orderAmountLimits, 'min', 999999) <= 30000 and getattr(o, 'unknown_things', {}).get('isAutoAccept', False)]

                    # Ищем Mirai
                    position = None
                    for i, offer in enumerate(offers, 1):
                        user_obj = getattr(offer, 'user', None)
                        if getattr(user_obj, 'nickname', '').startswith('Mirai'):
                            position = i
                            break

                    # Логика уведомлений
                    if position is not None:
                        if position == 1:
                            # На 1 месте - если был уведомлен (был не на 1), отправляем уведомление о возврате
                            if coins_state[coin]['notified'] and coins_state[coin]['last_position'] and coins_state[coin]['last_position'] > 1:
                                await context.bot.send_message(chat_id=user_id, text=f"✅ {coin}: Mirai вернулся на 1 место!")
                                # Сбрасываем флаг разрыва при возврате на 1 место, чтобы заново проверить
                                coins_state[coin]['gap_notified'] = False
                            coins_state[coin]['notified'] = False
                            coins_state[coin]['last_position'] = 1

                            # Проверяем разрыв со вторым местом
                            if len(offers) >= 2:
                                mirai_price = getattr(offers[0].price, 'value', 0)
                                second_price = getattr(offers[1].price, 'value', 0)
                                mirai_percent = (mirai_price / market_rate) * 100
                                second_percent = (second_price / market_rate) * 100
                                gap_percent = mirai_percent - second_percent

                                if gap_percent > 0.1 and not coins_state[coin]['gap_notified']:
                                    # Разрыв больше 0.1% - отправляем уведомление
                                    message = f"📉 {coin}: Можно спуститься ниже! Разрыв: {gap_percent:.2f}%\n\n"
                                    message += f"📊 ТОП-3 {coin}:\n\n"

                                    for i, offer in enumerate(offers[:3], 1):
                                        user_obj = getattr(offer, 'user', None)
                                        nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                                        offer_price = getattr(offer.price, 'value', 0)
                                        offer_pct = (offer_price / market_rate) * 100

                                        if nickname.startswith('Mirai'):
                                            message += f"🎯 {i}. {nickname}\n"
                                        else:
                                            message += f"{i}. {nickname}\n"
                                        message += f"{offer_price:.2f} ({offer_pct:.2f}%)\n\n"

                                    await context.bot.send_message(chat_id=user_id, text=message)
                                    coins_state[coin]['gap_notified'] = True
                                elif gap_percent <= 0.1:
                                    # Разрыв нормальный - сбрасываем флаг
                                    coins_state[coin]['gap_notified'] = False
                        elif position > 1 and not coins_state[coin]['notified']:
                            price = getattr(offers[position-1].price, 'value', 0)
                            price_percent = (price / market_rate) * 100

                            # Объединяем уведомление и ТОП-5 в одно сообщение
                            message = f"{coin}: Mirai на #{position} месте!\n\n"
                            message += f"📊 ТОП-5 {coin}:\n\n"

                            for i, offer in enumerate(offers[:5], 1):
                                user_obj = getattr(offer, 'user', None)
                                nickname = getattr(user_obj, 'nickname', 'N/A') if user_obj else 'N/A'
                                offer_price = getattr(offer.price, 'value', 0)
                                offer_pct = (offer_price / market_rate) * 100

                                if nickname.startswith('Mirai'):
                                    message += f"🎯 {i}. {nickname}\n"
                                else:
                                    message += f"{i}. {nickname}\n"
                                message += f"{offer_price:.2f} ({offer_pct:.2f}%)\n\n"

                            await context.bot.send_message(chat_id=user_id, text=message)

                            coins_state[coin]['notified'] = True
                            coins_state[coin]['last_position'] = position
                            # Сбрасываем флаг разрыва, когда упали с 1 места
                            coins_state[coin]['gap_notified'] = False
                        else:
                            coins_state[coin]['last_position'] = position
                    else:
                        coins_state[coin]['last_position'] = None

                except Exception as e:
                    print(f"Ошибка мониторинга {coin} для пользователя {user_id}: {e}")

            # Ждём 10 секунд перед следующей проверкой
            await asyncio.sleep(10)

    task = asyncio.create_task(monitor_multiple_coins())
    user_monitors_coins[user_id] = {
        'task': task,
        'filters': saved_filters,
        'coins_state': coins_state
    }

async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий текстовых кнопок"""
    text = update.message.text

    if text == "📊 Парсинг":
        await parse_market(update, context)
    elif text == "⚙️ Фильтры":
        await show_filters(update, context)
    elif text == "🔔 USDT":
        await start_monitor_usdt(update, context)
    elif text == "🔔 COINS":
        await start_monitor_coins(update, context)
    elif text == "🔕 Стоп мониторинг":
        await stop_monitor(update, context)
    elif text == "🎯 Позиции Mirai":
        await check_mirai_positions(update, context)

def main():
    """Запуск бота"""
    print("🤖 Запуск Telegram бота...")

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Установи BOT_TOKEN в коде!")
        print("Получи токен у @BotFather в Telegram")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("filters", show_filters))
    app.add_handler(CommandHandler("parse", parse_market))
    app.add_handler(CommandHandler("status", show_status))
    app.add_handler(CommandHandler("monitor", start_monitor))
    app.add_handler(CommandHandler("stop_monitor", stop_monitor))

    # Inline кнопки (меню фильтров)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Текстовые кнопки (главное меню)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    print("✓ Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
