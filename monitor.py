import os
import time
import logging
import sqlite3
import threading
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import telebot
from urllib.parse import urljoin

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('water_monitor.log')
    ]
)

# Проверка переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')

if not all([BOT_TOKEN, LOGIN, PASSWORD]) or ':' not in BOT_TOKEN:
    logging.error("Неверные настройки! Проверьте BOT_TOKEN, LOGIN и PASSWORD")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

class WaterMonitor:
    def __init__(self):
        self.driver = self.setup_driver()
        self.last_sale = None
        self.session_active = False

    def setup_driver(self):
        """Настройка ChromeDriver с улучшенными параметрами"""
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)
            return driver
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Улучшенная авторизация с обработкой различных сценариев"""
        for attempt in range(3):
            try:
                logging.info(f"Попытка авторизации #{attempt + 1}")
                self.driver.get(urljoin(BASE_URL, 'login'))
                time.sleep(2)

                # Ожидание и ввод данных
                login_field = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
                )
                login_field.clear()
                login_field.send_keys(LOGIN)

                password_field = self.driver.find_element(By.CSS_SELECTOR, "input[name='password']")
                password_field.clear()
                password_field.send_keys(PASSWORD)

                # Клик по кнопке входа
                submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit_button.click()

                # Проверка успешного входа
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Добро пожаловать') or contains(text(), 'Welcome')]"))
                )
                self.session_active = True
                logging.info("Авторизация успешна")
                return True

            except Exception as e:
                logging.warning(f"Ошибка авторизации: {str(e)[:200]}")
                if attempt < 2:
                    time.sleep(5)
                    try:
                        self.driver.refresh()
                    except:
                        self.driver = self.setup_driver()
                else:
                    logging.error("Все попытки авторизации провалились")
                    return False

    def check_sales(self):
        """Проверка новых продаж с улучшенной обработкой"""
        try:
            if not self.session_active and not self.login():
                return

            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1"))
            )

            rows = self.driver.find_elements(By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr")
            if not rows:
                return

            first_row = rows[0]
            cells = first_row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 6:
                return

            sale_data = {
                'number': cells[0].text.strip(),
                'address': cells[1].text.strip(),
                'time': cells[2].text.strip(),
                'liters': cells[3].text.strip(),
                'total': cells[4].text.strip(),
                'payment': self.get_payment_type(cells[5])
            }

            if not self.last_sale or sale_data['number'] != self.last_sale['number']:
                self.last_sale = sale_data
                self.send_alert(sale_data)

        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")
            self.session_active = False

    def get_payment_type(self, cell):
        """Определение типа оплаты с улучшенной логикой"""
        try:
            icon = cell.find_element(By.CSS_SELECTOR, "svg").get_attribute("outerHTML")
            if 'coin' in icon.lower():
                return "🪙 Монеты"
            elif 'bill' in icon.lower():
                return "💵 Купюры"
            elif 'card' in icon.lower():
                return "💳 Карта"
            return "❓ Неизвестно"
        except:
            return "❓ Неизвестно"

    def send_alert(self, sale_data):
        """Отправка уведомления о продаже"""
        message = (
            f"💰 <b>Новая продажа #{sale_data['number']}</b>\n"
            f"🏠 {sale_data['address']}\n"
            f"⏰ {sale_data['time']} | ⚖️{sale_data['liters']}л\n"
            f"💵 {sale_data['total']}\n"
            f"🔹 {sale_data['payment']}"
        )
        
        conn = sqlite3.connect('subscribers.db')
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM subscribers")
            for (chat_id,) in cursor.fetchall():
                try:
                    bot.send_message(chat_id, message)
                except Exception as e:
                    logging.error(f"Ошибка отправки: {e}")
        finally:
            conn.close()

def run_monitor():
    """Запуск мониторинга"""
    monitor = WaterMonitor()
    while True:
        try:
            monitor.check_sales()
            time.sleep(60)
        except Exception as e:
            logging.error(f"Ошибка мониторинга: {e}")
            time.sleep(60)

if __name__ == '__main__':
    # Инициализация БД
    with sqlite3.connect('subscribers.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    # Запуск бота в отдельном потоке
    bot_thread = threading.Thread(target=bot.infinity_polling, daemon=True)
    bot_thread.start()

    # Запуск мониторинга
    run_monitor()
