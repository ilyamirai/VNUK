"""
АВТОМАТИЧЕСКОЕ ПОЛУЧЕНИЕ P2P ТОКЕНА
Запускается раз в 8 минут и обновляет токен
"""
import sys
import io
import time
from wallet import Client
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def get_p2p_token():
    """Получает токен для P2P API с несколькими запасными методами"""
    c = None
    try:
        print(f"\n[{time.strftime('%H:%M:%S')}] Запускаю браузер...")
        c = Client(profile='wallet_parser', headless=False)

        # МЕТОД 1: Альтернативная версия /a/ (основной)
        print(f"[{time.strftime('%H:%M:%S')}] МЕТОД 1: Альтернативная версия /a/...")
        c.driver.get("https://web.telegram.org/a/#1985737506")
        time.sleep(7)

        clicked = False
        for attempt in range(10):
            try:
                time.sleep(1)
                print(f"[{time.strftime('%H:%M:%S')}] Попытка {attempt + 1}/10...")

                # XPath для кнопки меню /a/ версии
                try:
                    from selenium.webdriver.common.by import By
                    menu_button = c.driver.find_element(By.XPATH, "//button[contains(@class, 'bot-menu')]")
                    if menu_button:
                        menu_button.click()
                        result = 'menu_clicked'
                    else:
                        result = 'not_found'
                except:
                    result = 'not_found'

                if result == 'menu_clicked':
                    print(f"[{time.strftime('%H:%M:%S')}] ✓ Меню бота открыто!")
                    time.sleep(2)

                    # Ищем кнопку "Крипто Кошелёк" в меню
                    result2 = c.driver.execute_script("""
                        const allButtons = Array.from(document.querySelectorAll('button'));
                        for (let btn of allButtons) {
                            if (btn.innerHTML.includes('Крипто') || btn.textContent.includes('Крипто')) {
                                btn.click();
                                return 'clicked';
                            }
                        }
                        return 'not_found';
                    """)

                    if result2 == 'clicked':
                        print(f"[{time.strftime('%H:%M:%S')}] ✓ Кнопка 'Крипто Кошелёк' нажата!")
                        clicked = True
                        time.sleep(5)
                        break

            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Ошибка: {e}")

        # Проверяем токен после метода 1
        if clicked:
            token = check_for_token(c, 30)
            if token:
                return token

        # МЕТОД 2: Альтернативная версия Telegram Web (/a/)
        print(f"[{time.strftime('%H:%M:%S')}] МЕТОД 2: Пробую альтернативную версию Telegram...")
        c.driver.get("https://web.telegram.org/a/#1985737506")
        time.sleep(7)

        # Ищем меню бота в альтернативной версии
        clicked_a = False
        for attempt in range(10):
            try:
                time.sleep(1)
                print(f"[{time.strftime('%H:%M:%S')}] Попытка {attempt + 1}/10...")

                result = c.driver.execute_script("""
                    // Используем точный селектор для /a/ версии
                    const botMenuIcon = document.querySelector('#MiddleColumn > div.messages-layout > div.Transition > div > div.middle-column-footer > div.Composer.shown.mounted > div.composer-wrapper > div > button.Button.composer-action-button.bot-menu.open.default.translucent.round > i');
                    if (botMenuIcon) {
                        // Кликаем на родительскую кнопку
                        const menuButton = botMenuIcon.parentElement;
                        if (menuButton) {
                            menuButton.click();
                            console.log('Клик на меню бота');
                            return 'menu_clicked';
                        }
                    }

                    // Запасной вариант - ищем кнопку "Крипто"
                    const allButtons = Array.from(document.querySelectorAll('button'));
                    for (let btn of allButtons) {
                        if (btn.innerHTML.includes('Крипто') || btn.textContent.includes('Крипто')) {
                            btn.click();
                            return 'clicked';
                        }
                    }
                    return 'not_found';
                """)

                if result == 'menu_clicked':
                    print(f"[{time.strftime('%H:%M:%S')}] ✓ Меню бота открыто!")
                    time.sleep(2)

                    # Теперь ищем кнопку "Крипто Кошелёк"
                    result2 = c.driver.execute_script("""
                        const allButtons = Array.from(document.querySelectorAll('button'));
                        for (let btn of allButtons) {
                            if (btn.innerHTML.includes('Крипто') || btn.textContent.includes('Крипто')) {
                                btn.click();
                                return 'clicked';
                            }
                        }
                        return 'not_found';
                    """)

                    if result2 == 'clicked':
                        print(f"[{time.strftime('%H:%M:%S')}] ✓ Кнопка 'Крипто Кошелёк' нажата!")
                        clicked_a = True
                        time.sleep(5)
                        break

                elif result == 'clicked':
                    print(f"[{time.strftime('%H:%M:%S')}] ✓ Кнопка найдена и нажата!")
                    clicked_a = True
                    time.sleep(5)
                    break

            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Ошибка: {e}")

        if clicked_a:
            token = check_for_token(c, 30)
            if token:
                return token

        print(f"[{time.strftime('%H:%M:%S')}] ❌ Оба метода не сработали")
        return None

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Критическая ошибка: {e}")
        return None
    finally:
        if c:
            try:
                c.stop()
                print(f"[{time.strftime('%H:%M:%S')}] Браузер закрыт")
            except:
                pass

def check_for_token(c, max_wait):
    """Проверяет наличие токена в запросах"""
    print(f"[{time.strftime('%H:%M:%S')}] Жду токен (макс. {max_wait} сек)...")
    start_time = time.time()

    while time.time() - start_time < max_wait:
        for request in c.driver.requests:
            # Ищем запросы к walletbot.me (включая api/v1/coins/details и p2p)
            if 'walletbot.me' in request.url:
                if 'authorization' in request.headers:
                    auth = request.headers['authorization']
                    if 'Bearer' in auth:
                        token = auth.replace('Bearer ', '').strip()
                        print(f"[{time.strftime('%H:%M:%S')}] ✓ Токен найден! ({len(token)} символов)")
                        return token
        time.sleep(1)

    print(f"[{time.strftime('%H:%M:%S')}] ⚠ Токен не найден за {max_wait} сек")
    return None

def main():
    print("=" * 70)
    print("АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ P2P ТОКЕНА")
    print("=" * 70)
    print("\nТокен будет обновляться каждые 8 минут")
    print("Нажми Ctrl+C для остановки\n")

    while True:
        try:
            token = get_p2p_token()

            if token:
                with open('token.txt', 'w', encoding='utf-8') as f:
                    f.write(token)
                print(f"[{time.strftime('%H:%M:%S')}] ✓ Токен сохранён в token.txt\n")

                # Ждём 5 минут до следующего обновления
                wait_time = 300
                print(f"Следующее обновление через {wait_time//60} минут...\n")

                for i in range(wait_time, 0, -1):
                    mins = i // 60
                    secs = i % 60
                    print(f"\rОбновление через: {mins:02d}:{secs:02d}  ", end='', flush=True)
                    time.sleep(1)
                print()
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Токен не получен, повторяю попытку...\n")

        except KeyboardInterrupt:
            print("\n\n✓ Остановлено пользователем")
            break
        except Exception as e:
            print(f"\n[{time.strftime('%H:%M:%S')}] ❌ Ошибка: {e}")
            print("Повтор через 60 сек...\n")
            time.sleep(60)

if __name__ == '__main__':
    main()
