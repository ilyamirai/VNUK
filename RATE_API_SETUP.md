# Rate API Setup - Инструкция по настройке

## Что это?

Rate API - это простой HTTP сервер, который предоставляет актуальный рыночный курс USDT/RUB через Telegram Wallet API.

## Установка на VPS

### 1. Установите Flask (если еще не установлен)

```bash
pip install flask
```

### 2. Загрузите файл rate_api.py на VPS

Скопируйте файл `rate_api.py` в директорию с WalletParse на вашем VPS.

### 3. Запустите Rate API сервер

```bash
cd /path/to/WalletParse
python rate_api.py
```

Сервер запустится на порту 5000.

### 4. Для постоянной работы используйте systemd или screen

#### Вариант A: Через screen (простой способ)

```bash
screen -S rate_api
python rate_api.py
# Нажмите Ctrl+A затем D чтобы отсоединиться
```

Чтобы вернуться к сессии:
```bash
screen -r rate_api
```

#### Вариант B: Через systemd (рекомендуется для production)

Создайте файл `/etc/systemd/system/rate-api.service`:

```ini
[Unit]
Description=Rate API Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/WalletParse
ExecStart=/usr/bin/python3 rate_api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rate-api
sudo systemctl start rate-api
sudo systemctl status rate-api
```

### 5. Проверьте работу

```bash
curl http://localhost:5000/health
curl http://localhost:5000/api/rate/usdt-rub
```

## Настройка bank-management-system

### 1. Откройте файл `.env` в backend

```bash
cd bank-management-system/backend
nano .env
```

### 2. Добавьте или измените строку RATE_API_URL

Замените `YOUR_VPS_IP` на IP адрес вашего VPS:

```env
RATE_API_URL=http://YOUR_VPS_IP:5000/api/rate/usdt-rub
```

Примеры:
```env
# Если VPS на 192.168.1.100
RATE_API_URL=http://192.168.1.100:5000/api/rate/usdt-rub

# Если используете доменное имя
RATE_API_URL=http://yourdomain.com:5000/api/rate/usdt-rub

# Если на том же сервере
RATE_API_URL=http://localhost:5000/api/rate/usdt-rub
```

### 3. Перезапустите backend

```bash
# Остановите текущий процесс (Ctrl+C)
# Запустите снова
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

- `GET /api/rate/usdt-rub` - Получить курс USDT/RUB
- `GET /api/rate/<coin>/<currency>` - Получить курс любой монеты (USDT, BTC, TON, ETH, NOT)
- `GET /health` - Проверка работоспособности

## Примеры использования

```bash
# Курс USDT/RUB
curl http://YOUR_VPS_IP:5000/api/rate/usdt-rub

# Курс BTC/USD
curl http://YOUR_VPS_IP:5000/api/rate/btc/usd

# Курс TON/RUB
curl http://YOUR_VPS_IP:5000/api/rate/ton/rub

# Health check
curl http://YOUR_VPS_IP:5000/health
```

## Формат ответа

Успешный ответ:
```json
{
  "success": true,
  "rate": 106.12,
  "timestamp": "2025-10-18T04:48:15.123456",
  "source": "Telegram Wallet P2P API"
}
```

Ошибка:
```json
{
  "success": false,
  "error": "Token file not found"
}
```

## Безопасность

### Рекомендации:

1. **Используйте firewall** - разрешите доступ к порту 5000 только с IP адреса вашего bank-management-system сервера

```bash
# Пример для ufw
sudo ufw allow from YOUR_BANK_SYSTEM_IP to any port 5000
```

2. **Используйте HTTPS** - настройте nginx как reverse proxy с SSL

3. **Добавьте базовую аутентификацию** - если нужно ограничить доступ

## Troubleshooting

### Ошибка: "Token file not found"
- Убедитесь что файл `token.txt` существует в директории WalletParse
- Запустите `auto_token.py` для получения нового токена

### Ошибка: "Request attempts end"
- Токен истек, нужно обновить через `auto_token.py`
- Или запустите Telegram бота для автоматического обновления токена

### Порт 5000 занят
Измените порт в файле `rate_api.py` (последняя строка):
```python
app.run(host='0.0.0.0', port=5001, debug=False)  # Измените на другой порт
```

И обновите RATE_API_URL в `.env` файле bank-management-system.

## Логи

Логи Flask сервера выводятся в консоль. При использовании systemd:

```bash
sudo journalctl -u rate-api -f
```
