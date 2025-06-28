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
CHECK_INTERVAL = 60  # Интервал проверки в секундах
MAX_WAIT = 30  # Максимальное время ожидания элементов

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# Инициализация базы данных
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
        """Инициализация веб-драйвера с улучшенными настройками"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            logging.info("Драйвер Chrome успешно инициализирован")
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            self.send_admin_alert("🔴 Ошибка инициализации драйвера!")
            raise

    def login(self):
        """Улучшенная авторизация с обработкой ошибок"""
        for attempt in range(3):
            try:
                logging.info(f"Попытка авторизации {attempt + 1}")
                self.driver.get(urljoin(BASE_URL, 'login'))
                time.sleep(3)

                # Закрытие всплывающих окон
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                    ).find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
                    logging.info("Всплывающее окно закрыто")
                except:
                    pass

                # Ввод учетных данных
                WebDriverWait(self.driver, MAX_WAIT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
                ).send_keys(LOGIN)
                
                WebDriverWait(self.driver, MAX_WAIT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='password']"))
                ).send_keys(PASSWORD)
                
                # Клик по кнопке входа
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
                logging.warning(f"Ошибка авторизации (попытка {attempt + 1}): {str(e)[:200]}")
                if attempt < 2:
                    time.sleep(5)
                    try:
                        self.driver.refresh()
                    except:
                        self.initialize_driver()
        
        logging.error("Все попытки авторизации провалились")
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
            logging.info("Проверка новых продаж...")
            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr"))
            )
            
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr")
            if not rows:
                logging.info("Нет данных о продажах")
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
                    message = (
                        f"<b>💰 Новая продажа #{sale_data['number']}</b>\n"
                        f"🏠 <i>{sale_data['address']}</i>\n"
                        f"⏰ {sale_data['time']} | ⚖️ {sale_data['liters']} л\n"
                        f"💵 <b>{sale_data['total']}</b>\n"
                        f"🔹 {sale_data['payment']}"
                    )
                    self.send_notification(message)
                    logging.info(f"Отправлено уведомление: {message}")

        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")
            self.send_admin_alert("⚠️ Ошибка при проверке продаж")

    def send_notification(self, message):
        """Отправка уведомлений подписчикам"""
        conn = sqlite3.connect('subscribers.db')
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM subscribers')
        for (chat_id,) in cursor.fetchall():
            try:
                bot.send_message(chat_id, message)
                logging.info(f"Уведомление отправлено в чат {chat_id}")
            except Exception as e:
                logging.error(f"Ошибка отправки в чат {chat_id}: {e}")
        conn.close()

    def send_admin_alert(self, message):
        """Отправка уведомления администратору"""
        if ADMIN_CHAT_ID:
            try:
                bot.send_message(ADMIN_CHAT_ID, message)
            except Exception as e:
                logging.error(f"Ошибка отправки админ-уведомления: {e}")

# Команды бота
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, 
        "👋 Привет! Я бот для мониторинга продаж воды.\n\n"
        "📋 Команды:\n"
        "/subscribe - подписаться на уведомления\n"
        "/unsubscribe - отписаться\n"
        "/id - узнать ваш chat_id"
    )

@bot.message_handler(commands=['subscribe'])
def subscribe(message):
    conn = sqlite3.connect('subscribers.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT OR IGNORE INTO subscribers (chat_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
            (message.chat.id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        )
        conn.commit()
        bot.reply_to(message, "✅ Вы подписаны на уведомления!" if cursor.rowcount > 0 else "ℹ️ Вы уже подписаны")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
    finally:
        conn.close()

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe(message):
    conn = sqlite3.connect('subscribers.db')
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM subscribers WHERE chat_id = ?', (message.chat.id,))
        conn.commit()
        bot.reply_to(message, "✅ Вы отписались" if cursor.rowcount > 0 else "ℹ️ Вы не были подписаны")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
    finally:
        conn.close()

@bot.message_handler(commands=['id'])
def send_id(message):
    bot.reply_to(message, f"Ваш chat_id: <code>{message.chat.id}</code>")

def run_bot():
    """Запуск бота в отдельном потоке"""
    logging.info("Бот запущен")
    bot.infinity_polling()

if __name__ == '__main__':
    # Запуск бота
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запуск мониторинга
    monitor = AliveWaterMonitor()
    while True:
        try:
            if monitor.login():
                monitor.check_sales()
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Критическая ошибка: {e}")
            time.sleep(60)
