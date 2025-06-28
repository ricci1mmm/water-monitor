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

# Конфигурация
BOT_TOKEN = os.environ['BOT_TOKEN']  # Берем из переменных окружения GitHub
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.environ['LOGIN']
PASSWORD = os.environ['PASSWORD']
CHECK_INTERVAL = 60

# Проверка токена
if ':' not in BOT_TOKEN:
    logging.error("Токен бота должен содержать ':' (формат: 123456789:ABCdef...)")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

class WaterMonitor:
    def __init__(self):
        self.driver = self.init_driver()
        self.last_sale = None

    def init_driver(self):
        """Инициализация ChromeDriver для GitHub Actions"""
        try:
            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--headless=new')
            
            service = Service(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=options)
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Авторизация на сайте"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            time.sleep(3)
            
            # Ввод данных
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
                return

            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
            )

            # Здесь добавьте вашу логику обработки продаж
            # ...

        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")

def run_monitor():
    monitor = WaterMonitor()
    while True:
        monitor.check_sales()
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    # Инициализация БД
    with sqlite3.connect('subscribers.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    # Запуск
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    run_monitor()
