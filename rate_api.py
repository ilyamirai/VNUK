"""
Универсальный HTTP API для работы с Telegram Wallet P2P
Использует токен wallet из token.txt
"""

from flask import Flask, jsonify, request
from wallet import Wallet
from datetime import datetime

app = Flask(__name__)


def get_wallet_instance():
    """Получить экземпляр Wallet с токеном из файла"""
    return Wallet.token_from_file('token.txt')


@app.route('/api/rate/usdt-rub', methods=['GET'])
def get_usdt_rub_rate():
    """
    Получить текущий рыночный курс USDT/RUB

    Returns:
        {
            'success': bool,
            'rate': float,
            'timestamp': str (ISO format),
            'source': str,
            'error': str (optional)
        }
    """
    try:
        w = get_wallet_instance()
        market_rate_data = w.get_p2p_rate(base='USDT', quote='RUB')
        rate = float(market_rate_data['rate'])

        return jsonify({
            'success': True,
            'rate': rate,
            'timestamp': datetime.now().isoformat(),
            'source': 'Telegram Wallet P2P API'
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/rate/<coin>/<currency>', methods=['GET'])
def get_rate(coin, currency):
    """
    Получить курс любой монеты

    Args:
        coin: Код монеты (USDT, BTC, TON, ETH, NOT)
        currency: Код валюты (RUB, USD)

    Returns:
        {
            'success': bool,
            'rate': float,
            'coin': str,
            'currency': str,
            'timestamp': str (ISO format),
            'source': str,
            'error': str (optional)
        }
    """
    try:
        w = get_wallet_instance()
        market_rate_data = w.get_p2p_rate(base=coin.upper(), quote=currency.upper())
        rate = float(market_rate_data['rate'])

        return jsonify({
            'success': True,
            'rate': rate,
            'coin': coin.upper(),
            'currency': currency.upper(),
            'timestamp': datetime.now().isoformat(),
            'source': 'Telegram Wallet P2P API'
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/p2p/market', methods=['GET'])
def get_p2p_market():
    """
    Универсальный эндпоинт для получения P2P маркета с фильтрами

    Query Parameters:
        base_currency: str (default: USDT) - Базовая валюта
        quote_currency: str (default: RUB) - Валюта котировки
        offer_type: str (default: sell) - Тип оффера (buy/sell)
        limit: int (default: 50) - Количество офферов
        merchant_verified: bool (default: true) - Только верифицированные
        payment_methods: str - Методы оплаты через запятую (например: sberbankru,sbp)
        desired_amount: float - Желаемая сумма сделки
        top1: bool (default: false) - Вернуть только топ-1 оффер

    Returns:
        {
            'success': bool,
            'offers': list or dict (если top1=true),
            'count': int,
            'timestamp': str,
            'filters': dict,
            'error': str (optional)
        }
    """
    try:
        w = get_wallet_instance()

        # Парсим параметры
        base_currency = request.args.get('base_currency', 'USDT').upper()
        quote_currency = request.args.get('quote_currency', 'RUB').upper()
        offer_type = request.args.get('offer_type', 'PURCHASE').upper()  # PURCHASE или SALE
        limit = int(request.args.get('limit', 50))
        merchant_verified = request.args.get('merchant_verified', 'TRUSTED')  # TRUSTED, VERIFIED или пусто
        desired_amount = request.args.get('desired_amount', type=float)
        top1_only = request.args.get('top1', 'false').lower() == 'true'

        # Парсим методы оплаты
        payment_methods_str = request.args.get('payment_methods')
        payment_methods = None
        if payment_methods_str:
            payment_methods = [m.strip() for m in payment_methods_str.split(',')]

        # Вызываем API
        kwargs = {
            'base_currency_code': base_currency,
            'quote_currency_code': quote_currency,
            'offer_type': offer_type,
            'limit': limit,
            'merchant_verified': merchant_verified
        }

        if payment_methods:
            kwargs['payment_method_codes'] = payment_methods

        if desired_amount:
            kwargs['desired_amount'] = desired_amount

        offers = w.get_p2p_market(**kwargs)

        if not offers:
            return jsonify({
                'success': False,
                'error': 'No offers found with specified filters',
                'filters': kwargs
            }), 404

        # Если нужен только топ-1
        if top1_only:
            top_offer = offers[0]
            return jsonify({
                'success': True,
                'offer': {
                    'price': float(top_offer['price']),
                    'amount': top_offer.get('amount'),
                    'min_amount': top_offer.get('min_amount'),
                    'max_amount': top_offer.get('max_amount'),
                    'available': top_offer.get('available'),
                    'payment_methods': top_offer.get('payment_methods', []),
                    'merchant': top_offer.get('merchant', {})
                },
                'timestamp': datetime.now().isoformat(),
                'filters': kwargs
            })

        # Возвращаем все офферы
        simplified_offers = []
        for offer in offers:
            simplified_offers.append({
                'price': float(offer['price']),
                'amount': offer.get('amount'),
                'min_amount': offer.get('min_amount'),
                'max_amount': offer.get('max_amount'),
                'available': offer.get('available'),
                'payment_methods': offer.get('payment_methods', []),
                'merchant': offer.get('merchant', {})
            })

        return jsonify({
            'success': True,
            'offers': simplified_offers,
            'count': len(simplified_offers),
            'timestamp': datetime.now().isoformat(),
            'filters': kwargs
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/p2p/payment-methods', methods=['GET'])
def get_payment_methods():
    """
    Получить доступные методы оплаты для валюты

    Query Parameters:
        currency: str (default: RUB) - Код валюты

    Returns:
        {
            'success': bool,
            'currency': str,
            'payment_methods': list,
            'error': str (optional)
        }
    """
    try:
        w = get_wallet_instance()
        currency = request.args.get('currency', 'RUB').upper()

        methods = w.get_p2p_payment_methods_by_currency(currency_code=currency)

        return jsonify({
            'success': True,
            'currency': currency,
            'payment_methods': methods,
            'timestamp': datetime.now().isoformat()
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/balances', methods=['GET'])
def get_balances():
    """
    Получить балансы кошелька

    Returns:
        {
            'success': bool,
            'balances': list,
            'error': str (optional)
        }
    """
    try:
        w = get_wallet_instance()
        balances = w.get_user_balances()

        return jsonify({
            'success': True,
            'balances': balances,
            'timestamp': datetime.now().isoformat()
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/p2p/supported-fiat', methods=['GET'])
def get_supported_fiat():
    """
    Получить поддерживаемые фиатные валюты

    Returns:
        {
            'success': bool,
            'fiat_currencies': list,
            'error': str (optional)
        }
    """
    try:
        w = get_wallet_instance()
        fiat = w.get_supported_p2p_fiat()

        return jsonify({
            'success': True,
            'fiat_currencies': fiat,
            'timestamp': datetime.now().isoformat()
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Обратная совместимость со старым эндпоинтом
@app.route('/api/rate/usdt-rub/buy-top1', methods=['GET'])
def get_buy_top1_rate():
    """
    DEPRECATED: Используйте /api/p2p/market с параметрами

    Получить топ-1 курс покупки USDT с фильтрами Сбербанк+СБП
    """
    try:
        w = get_wallet_instance()

        offers = w.get_p2p_market(
            base_currency_code='USDT',
            quote_currency_code='RUB',
            offer_type='PURCHASE',
            limit=50,
            merchant_verified='TRUSTED',
            payment_method_codes=['sberbankru', 'sbp']
        )

        if not offers:
            return jsonify({
                'success': False,
                'error': 'No offers found'
            }), 404

        top_offer = offers[0]
        rate = float(top_offer['price'])

        return jsonify({
            'success': True,
            'rate': rate,
            'timestamp': datetime.now().isoformat(),
            'source': 'Telegram Wallet P2P Top-1 Buy Offer',
            'deprecated': 'Use /api/p2p/market?top1=true&payment_methods=sberbankru,sbp instead'
        })

    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'debug': 'buy-top1 endpoint'
        }), 500


@app.route('/test-market', methods=['GET'])
def test_market():
    """Test get_p2p_market без фильтров"""
    try:
        w = get_wallet_instance()
        # Минимальный запрос без фильтров - ТОЧНО КАК В telegram_bot
        offers = w.get_p2p_market(
            base_currency_code='USDT',
            quote_currency_code='RUB',
            offer_type='PURCHASE',  # ИСПРАВЛЕНО: было 'sell'
            limit=50,
            merchant_verified='TRUSTED'
        )
        return jsonify({
            'success': True,
            'count': len(offers),
            'first_price': float(offers[0]['price']) if offers else None
        })
    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


@app.route('/', methods=['GET'])
def index():
    """API Documentation"""
    return jsonify({
        'name': 'Telegram Wallet P2P API',
        'version': '2.0',
        'endpoints': {
            'rates': {
                'GET /api/rate/usdt-rub': 'Get USDT/RUB market rate',
                'GET /api/rate/<coin>/<currency>': 'Get any coin rate',
                'GET /api/rate/usdt-rub/buy-top1': '[DEPRECATED] Get top-1 buy rate with Sberbank+SBP filters'
            },
            'p2p': {
                'GET /api/p2p/market': 'Get P2P market offers with filters (see params)',
                'GET /api/p2p/payment-methods': 'Get available payment methods',
                'GET /api/p2p/supported-fiat': 'Get supported fiat currencies'
            },
            'wallet': {
                'GET /api/balances': 'Get wallet balances'
            },
            'system': {
                'GET /health': 'Health check',
                'GET /': 'This documentation'
            }
        },
        'examples': {
            'Top-1 buy rate with filters': '/api/p2p/market?base_currency=USDT&quote_currency=RUB&offer_type=sell&top1=true&payment_methods=sberbankru,sbp&desired_amount=55000',
            'Get 10 best sell offers': '/api/p2p/market?offer_type=buy&limit=10',
            'Get payment methods for RUB': '/api/p2p/payment-methods?currency=RUB'
        }
    })


if __name__ == '__main__':
    print("=" * 60)
    print("Telegram Wallet P2P API v2.0")
    print("=" * 60)
    print("\nMain endpoints:")
    print("  GET  /                              - API documentation")
    print("  GET  /health                        - Health check")
    print("\nRate endpoints:")
    print("  GET  /api/rate/usdt-rub             - USDT/RUB rate")
    print("  GET  /api/rate/<coin>/<currency>    - Any coin rate")
    print("\nP2P Market:")
    print("  GET  /api/p2p/market                - P2P offers with filters")
    print("  GET  /api/p2p/payment-methods       - Payment methods")
    print("  GET  /api/p2p/supported-fiat        - Supported fiat")
    print("\nWallet:")
    print("  GET  /api/balances                  - Wallet balances")
    print("\n" + "=" * 60)
    print(f"Server running on http://0.0.0.0:5000")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False)
