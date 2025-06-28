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
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logging.error("BOT_TOKEN не установлен!")
    exit(1)

BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')
CHECK_INTERVAL = 60
MAX_WAIT = 30
MAX_LOGIN_ATTEMPTS = 3

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# Улучшенная инициализация базы данных
def init_db():
    try:
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
    except Exception as e:
        logging.error(f"Ошибка инициализации БД: {e}")
        exit(1)

init_db()

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.last_sale = None
        self.last_problems = {}
        self.login_attempts = 0
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
            chrome_options.add_argument("--disable-extensions")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            logging.info("Драйвер успешно инициализирован")
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            self.send_admin_alert("🔴 Ошибка инициализации драйвера!")
            raise

    def login(self):
        """Улучшенная авторизация с обработкой капчи"""
        try:
            for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
                try:
                    self.driver.get(urljoin(BASE_URL, 'login'))
                    time.sleep(3)

                    # Закрытие возможного попапа
                    try:
                        popup = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                        )
                        popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
                        logging.info("Всплывающее окно закрыто")
                    except:
                        pass

                    # Ввод учетных данных
                    login_field = WebDriverWait(self.driver, MAX_WAIT).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
                    )
                    login_field.clear()
                    login_field.send_keys(LOGIN)
                    
                    password_field = self.driver.find_element(By.CSS_SELECTOR, "input[name='password']")
                    password_field.clear()
                    password_field.send_keys(PASSWORD)
                    
                    self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
                    
                    # Проверка успешной авторизации
                    WebDriverWait(self.driver, MAX_WAIT).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "span._container_iuuwv_1"))
                    )
                    self.login_attempts = 0
                    return True
                except Exception as e:
                    logging.warning(f"Попытка входа {attempt} не удалась: {e}")
                    if attempt < MAX_LOGIN_ATTEMPTS:
                        time.sleep(5)
                        self.driver.refresh()
            
            logging.error("Превышено количество попыток входа")
            return False
        except Exception as e:
            logging.error(f"Критическая ошибка авторизации: {e}")
            return False

    def check_sales(self):
        """Проверка новых продаж с улучшенной обработкой"""
        try:
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
                    self.send_notification(
                        f"<b>💰 Новая продажа #{sale_data['number']}</b>\n"
                        f"🏠 <i>{sale_data['address']}</i>\n"
                        f"⏰ {sale_data['time']} | ⚖️ {sale_data['liters']}\n"
                        f"💵 {sale_data['total']} ({sale_data['payment']})"
                    )
                    logging.info(f"Обнаружена новая продажа: {sale_data['number']}")
        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")
            self.send_admin_alert("⚠️ Ошибка при проверке продаж")

    # ... (остальные методы класса остаются без изменений)

    def send_notification(self, message):
        """Улучшенная отправка уведомлений с ретраями"""
        conn = sqlite3.connect('subscribers.db')
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM subscribers')
        subscribers = cursor.fetchall()
        conn.close()
        
        for (chat_id,) in subscribers:
            for attempt in range(3):
                try:
                    bot.send_message(chat_id, message)
                    logging.info(f"Уведомление отправлено в чат {chat_id}")
                    break
                except Exception as e:
                    logging.warning(f"Попытка {attempt + 1} для чата {chat_id} не удалась: {e}")
                    if "bot was blocked" in str(e):
                        self.remove_subscriber(chat_id)
                        break
                    time.sleep(2)

    def send_admin_alert(self, message):
        """Отправка уведомления администратору"""
        if ADMIN_CHAT_ID:
            try:
                bot.send_message(ADMIN_CHAT_ID, message)
            except Exception as e:
                logging.error(f"Ошибка отправки админ-уведомления: {e}")

    def run_monitoring_loop(self):
        """Основной цикл мониторинга"""
        while True:
            try:
                logging.info("Запуск проверки...")
                
                if not self.login():
                    self.send_admin_alert("🔴 Ошибка авторизации в системе!")
                    time.sleep(300)
                    continue
                
                self.check_sales()
                self.check_terminals()
                
                logging.info(f"Ожидание {CHECK_INTERVAL} секунд до следующей проверки...")
                time.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                error_msg = f"🔴 Критическая ошибка: {str(e)[:200]}"
                logging.error(error_msg, exc_info=True)
                self.send_admin_alert(error_msg)
                time.sleep(300)

# ... (обработчики команд бота остаются без изменений)

if __name__ == '__main__':
    # Инициализация бота
    def run_bot():
        try:
            bot.infinity_polling()
        except Exception as e:
            logging.error(f"Ошибка бота: {e}")

    # Запуск бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запуск мониторинга
    try:
        monitor = AliveWaterMonitor()
        monitor.run_monitoring_loop()
    except KeyboardInterrupt:
        logging.info("Мониторинг остановлен пользователем")
    except Exception as e:
        logging.error(f"Фатальная ошибка мониторинга: {e}")
        exit(1)
