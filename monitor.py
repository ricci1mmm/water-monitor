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

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN') or 'ВАШ_ТОКЕН_БОТА'
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN') or 'ВАШ_ЛОГИН'
PASSWORD = os.getenv('PASSWORD') or 'ВАШ_ПАРОЛЬ'
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')  # Необязательно
CHECK_INTERVAL = 60  # Интервал проверки в секундах
MAX_WAIT = 30  # Максимальное время ожидания элементов

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# Инициализация базы данных подписчиков
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
        """Инициализация веб-драйвера Chrome"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            logging.info("Драйвер Chrome успешно инициализирован")
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Авторизация в системе AliveWater"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            time.sleep(2)

            # Закрытие всплывающего окна, если есть
            try:
                popup = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                )
                popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
                logging.info("Всплывающее окно закрыто")
            except:
                pass

            # Ввод учетных данных
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            ).send_keys(LOGIN)
            
            self.driver.find_element(By.CSS_SELECTOR, "input[name='password']").send_keys(PASSWORD)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            # Проверка успешной авторизации
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span._container_iuuwv_1"))
            )
            logging.info("Авторизация успешна")
            return True
        except Exception as e:
            logging.error(f"Ошибка авторизации: {e}")
            return False

    def get_payment_method(self, cell):
        """Определение способа оплаты с иконками"""
        try:
            # Проверка по классам элемента
            classes = cell.get_attribute("class")
            if 'coin' in classes.lower():
                return "🪙 Монеты"
            elif 'bill' in classes.lower():
                return "💵 Купюры"
            elif 'card' in classes.lower():
                return "💳 Карта"
            
            # Проверка по SVG иконкам
            icons = cell.find_elements(By.CSS_SELECTOR, "svg")
            if icons:
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
        """Проверка новых продаж воды"""
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
            if ADMIN_CHAT_ID:
                bot.send_message(ADMIN_CHAT_ID, f"⚠️ Ошибка проверки продаж: {str(e)[:200]}")

    def send_notification(self, message):
        """Отправка уведомления всем подписчикам"""
        conn = sqlite3.connect('subscribers.db')
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM subscribers')
        subscribers = cursor.fetchall()
        conn.close()
        
        for (chat_id,) in subscribers:
            try:
                bot.send_message(chat_id, message)
                logging.info(f"Уведомление отправлено в чат {chat_id}")
            except Exception as e:
                logging.error(f"Ошибка отправки в чат {chat_id}: {e}")
                if "bot was blocked" in str(e):
                    self.remove_subscriber(chat_id)

    def remove_subscriber(self, chat_id):
        """Удаление подписчика при блокировке бота"""
        conn = sqlite3.connect('subscribers.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM subscribers WHERE chat_id = ?', (chat_id,))
        conn.commit()
        conn.close()
        logging.info(f"Удален подписчик {chat_id} (блокировка бота)")

    def run(self):
        """Основной цикл мониторинга"""
        logging.info("Сервис мониторинга запущен")
        while True:
            try:
                if not self.login():
                    time.sleep(60)
                    continue
                
                self.check_sales()
                time.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                logging.error(f"Ошибка в основном цикле: {e}")
                time.sleep(60)

# Команды бота
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, 
        "👋 Привет! Я бот для мониторинга продаж воды.\n\n"
        "📋 Команды:\n"
        "/subscribe - подписаться на уведомления\n"
        "/unsubscribe - отписаться\n"
        "/id - узнать ваш chat_id\n\n"
        "Автоматически присылаю уведомления о новых продажах."
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
    bot.infinity_polling()

if __name__ == '__main__':
    # Запуск бота
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запуск мониторинга
    monitor = AliveWaterMonitor()
    monitor.run()
