import os
import time
import logging
import sqlite3
import threading
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import telebot
from urllib.parse import urljoin
from webdriver_manager.chrome import ChromeDriverManager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('water_monitor.log')
    ]
)

# Проверка конфигурации
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN or ':' not in BOT_TOKEN:
    logging.error("Неверный формат BOT_TOKEN! Должен быть в формате 123456789:ABCdef...")
    exit(1)

BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')
CHECK_INTERVAL = 60
MAX_WAIT = 30

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.last_sale = None
        self.initialize_driver()

    def initialize_driver(self):
        """Инициализация веб-драйвера с улучшенными настройками"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-gpu")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            logging.info("Драйвер Chrome успешно инициализирован")
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Улучшенная авторизация с обработкой ошибок"""
        for attempt in range(3):
            try:
                self.driver.get(urljoin(BASE_URL, 'login'))
                time.sleep(3)

                # Закрытие всплывающих окон
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                    ).find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
                except:
                    pass

                # Ввод учетных данных
                WebDriverWait(self.driver, MAX_WAIT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
                ).send_keys(LOGIN)
                
                WebDriverWait(self.driver, MAX_WAIT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='password']"))
                ).send_keys(PASSWORD)
                
                WebDriverWait(self.driver, MAX_WAIT).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
                ).click()

                # Проверка успешного входа
                WebDriverWait(self.driver, MAX_WAIT).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Добро пожаловать') or contains(text(), 'Welcome')]"))
                )
                logging.info("Авторизация успешна")
                return True

            except Exception as e:
                logging.warning(f"Попытка входа {attempt + 1} не удалась: {str(e)[:200]}")
                if attempt < 2:
                    time.sleep(5)
                    self.driver.refresh()
        
        logging.error("Все попытки авторизации провалились")
        return False

    # ... (остальные методы остаются без изменений)

if __name__ == '__main__':
    try:
        monitor = AliveWaterMonitor()
        if monitor.login():
            while True:
                monitor.check_sales()
                time.sleep(CHECK_INTERVAL)
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
    finally:
        if hasattr(monitor, 'driver') and monitor.driver:
            monitor.driver.quit()
