"""
Простой HTTP API для предоставления рыночного курса USDT/RUB
Использует токен wallet из token.txt
"""

from flask import Flask, jsonify
from wallet import Wallet
from datetime import datetime

app = Flask(__name__)


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
        # Загружаем токен из файла
        w = Wallet.token_from_file('token.txt')

        # Получаем рыночный курс USDT/RUB
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
        # Загружаем токен из файла
        w = Wallet.token_from_file('token.txt')

        # Получаем рыночный курс
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


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    print("Starting Rate API server...")
    print("Endpoints:")
    print("   GET /api/rate/usdt-rub - Get USDT/RUB rate")
    print("   GET /api/rate/<coin>/<currency> - Get any coin rate")
    print("   GET /health - Health check")
    print("\nServer running on http://0.0.0.0:5000")

    app.run(host='0.0.0.0', port=5000, debug=False)
