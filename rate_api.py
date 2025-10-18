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


@app.route('/api/wallet/proxy', methods=['POST'])
def wallet_proxy():
    """
    Универсальный прокси для вызова методов Wallet API

    Принимает JSON:
    {
        "method": "get_p2p_market",
        "params": {
            "base_currency_code": "USDT",
            "quote_currency_code": "RUB",
            "offer_type": "PURCHASE",
            ...
        }
    }

    Возвращает сырой результат от Wallet API
    """
    try:
        data = request.get_json()

        if not data or 'method' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: method'
            }), 400

        method_name = data['method']
        params = data.get('params', {})

        # Получаем Wallet с токеном
        w = get_wallet_instance()

        # Проверяем что метод существует
        if not hasattr(w, method_name):
            return jsonify({
                'success': False,
                'error': f'Unknown method: {method_name}'
            }), 400

        # Вызываем метод
        method = getattr(w, method_name)
        result = method(**params)

        # Возвращаем результат как есть
        return jsonify({
            'success': True,
            'result': result,
            'timestamp': datetime.now().isoformat()
        })

    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Token file not found'
        }), 500

    except TypeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid parameters for method: {str(e)}'
        }), 400

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
        'name': 'Telegram Wallet P2P API Proxy',
        'version': '3.0',
        'endpoints': {
            'POST /api/wallet/proxy': 'Universal proxy for Wallet methods',
            'GET  /health': 'Health check',
            'GET  /': 'This documentation'
        },
        'example': {
            'url': '/api/wallet/proxy',
            'method': 'POST',
            'body': {
                'method': 'get_p2p_market',
                'params': {
                    'base_currency_code': 'USDT',
                    'quote_currency_code': 'RUB',
                    'offer_type': 'PURCHASE',
                    'limit': 50,
                    'merchant_verified': 'TRUSTED',
                    'payment_method_codes': ['sberbankru', 'sbp']
                }
            }
        }
    })


if __name__ == '__main__':
    print("=" * 60)
    print("Telegram Wallet P2P API Proxy v3.0")
    print("=" * 60)
    print("\nEndpoints:")
    print("  POST /api/wallet/proxy    - Universal proxy")
    print("  GET  /health              - Health check")
    print("  GET  /                    - Documentation")
    print("\n" + "=" * 60)
    print(f"Server running on http://0.0.0.0:5000")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False)
