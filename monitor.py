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

def validate_config():
    """Проверка обязательных переменных"""
    required_vars = {
        'BOT_TOKEN': os.getenv('BOT_TOKEN'),
        'LOGIN': os.getenv('LOGIN'),
        'PASSWORD': os.getenv('PASSWORD')
    }
    
    errors = []
    for name, value in required_vars.items():
        if not value:
            errors.append(f"Не задана переменная {name}")
        elif name == 'BOT_TOKEN' and ':' not in value:
            errors.append("Токен бота должен содержать ':' (формат: 123456789:ABCdef...)")
    
    if errors:
        for error in errors:
            logging.error(error)
        exit(1)

# Загрузка конфигурации
validate_config()
BOT_TOKEN = os.getenv('BOT_TOKEN')
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')
CHECK_INTERVAL = 60
MAX_WAIT = 30

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# Инициализация БД
def init_db():
    conn = sqlite3.connect('subscribers.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.last_sale = None
        self.initialize_driver()

    def initialize_driver(self):
        """Инициализация ChromeDriver"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            logging.info("Драйвер Chrome инициализирован")
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Авторизация на сайте"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            time.sleep(2)

            try:
                popup = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                )
                popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
            except:
                pass

            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            ).send_keys(LOGIN)
            
            self.driver.find_element(By.CSS_SELECTOR, "input[name='password']").send_keys(PASSWORD)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span._container_iuuwv_1"))
            )
            return True
        except Exception as e:
            logging.error(f"Ошибка авторизации: {e}")
            return False

    def get_payment_method(self, cell):
        """Определение способа оплаты"""
        try:
            icons = cell.find_elements(By.CSS_SELECTOR, "svg")
            if not icons:
                return "❓ Неизвестно"
                
            icon_html = icons[0].get_attribute("outerHTML")
            
            if 'coin' in icon_html.lower():
                return "🪙 Монеты"
            elif 'bill' in icon_html.lower():
                return "💵 Купюры"
            elif 'card' in icon_html.lower():
                return "💳 Карта"
            return "❓ Неизвестно"
        except Exception as e:
            logging.warning(f"Ошибка определения оплаты: {e}")
            return "❓ Неизвестно"

    def check_sales(self):
        """Проверка новых продаж"""
        try:
            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr"))
            )
            
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr")
            if not rows:
                return

            first_row = rows[0]
            cells = first_row.find_elements(By.TAG_NAME, "td")
            
            if len(cells) >= 6:
                sale_data = {
                    'number': cells[0].text.strip(),
                    'address': cells[1].text.strip(),
                    'time': cells[2].text.strip(),
                    'liters': cells[3].text.strip(),
                    'total': cells[4].text.strip(),
                    'payment': self.get_payment_method(cells[5])
                }
                
                if not self.last_sale or sale_data['number'] != self.last_sale['number']:
                    self.last_sale = sale_data
                    self.send_notification(
                        f"<b>💰 Новая продажа #{sale_data['number']}</b>\n"
                        f"🏠 <i>{sale_data['address']}</i>\n"
                        f"⏰ {sale_data['time']} | ⚖️ {sale_data['liters']} л\n"
                        f"💵 <b>{sale_data['total']}</b>\n"
                        f"🔹 {sale_data['payment']}"
                    )
        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")

    def send_notification(self, message):
        """Отправка уведомлений"""
        conn = sqlite3.connect('subscribers.db')
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM subscribers')
        for (chat_id,) in cursor.fetchall():
            try:
                bot.send_message(chat_id, message)
            except Exception as e:
                logging.error(f"Ошибка отправки в чат {chat_id}: {e}")
        conn.close()

# Команды бота
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Бот мониторинга продаж воды. Используйте /subscribe")

@bot.message_handler(commands=['subscribe'])
def subscribe(message):
    conn = sqlite3.connect('subscribers.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO subscribers (chat_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
        (message.chat.id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    )
    conn.commit()
    conn.close()
    bot.reply_to(message, "✅ Вы подписаны на уведомления!")

@bot.message_handler(commands=['id'])
def send_id(message):
    bot.reply_to(message, f"Ваш ID: <code>{message.chat.id}</code>")

def run_bot():
    """Запуск бота"""
    bot.infinity_polling()

if __name__ == '__main__':
    # Запуск в двух потоках
    threading.Thread(target=run_bot, daemon=True).start()
    
    monitor = AliveWaterMonitor()
    while True:
        try:
            if monitor.login():
                monitor.check_sales()
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Ошибка: {e}")
            time.sleep(60)
