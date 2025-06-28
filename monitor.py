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

if not all([BOT_TOKEN, LOGIN, PASSWORD]):
    logging.error("Не заданы обязательные переменные окружения!")
    exit(1)

if ':' not in BOT_TOKEN:
    logging.error("Неверный формат BOT_TOKEN! Должен быть в формате 123456789:ABCdef...")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

class WaterMonitor:
    def __init__(self):
        self.driver = self.setup_driver()
        self.last_sale = None

    def setup_driver(self):
        """Настройка ChromeDriver для GitHub Actions"""
        try:
            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--headless=new')
            options.add_argument('--window-size=1920,1080')
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)
            return driver
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Авторизация на сайте"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            
            # Ожидание и ввод данных
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            ).send_keys(LOGIN)
            
            self.driver.find_element(By.CSS_SELECTOR, "input[name='password']").send_keys(PASSWORD)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            # Проверка успешного входа
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Добро пожаловать')]"))
            )
            return True
        except Exception as e:
            logging.error(f"Ошибка авторизации: {e}")
            return False

    def check_sales(self):
        """Проверка новых продаж"""
        try:
            if not self.login():
                logging.error("Не удалось авторизоваться, пропускаем проверку")
                return

            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
            )

            # Здесь добавьте вашу логику обработки продаж
            # Например:
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            if rows:
                first_row = rows[0]
                cells = first_row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 6:
                    sale_data = {
                        'number': cells[0].text,
                        'address': cells[1].text,
                        'time': cells[2].text,
                        'liters': cells[3].text,
                        'total': cells[4].text,
                        'payment': cells[5].text
                    }
                    logging.info(f"Найдена продажа: {sale_data}")

        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")

def run_monitor():
    monitor = WaterMonitor()
    while True:
        monitor.check_sales()
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

    # Запуск бота и мониторинга
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    run_monitor()
