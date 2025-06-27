
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
    handlers=[logging.StreamHandler()]
)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')  # Необязательный параметр
CHECK_INTERVAL = 60
MAX_WAIT = 30
MAX_LOGIN_ATTEMPTS = 3

bot = telebot.TeleBot(BOT_TOKEN)

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
        self.last_problems = {}
        self.login_attempts = 0
        self.initialize_driver()

    def initialize_driver(self):
        """Инициализация веб-драйвера"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1200,800")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            logging.info("Драйвер успешно инициализирован")
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            raise

    def login(self):
        """Авторизация в системе"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            time.sleep(2)

            try:
                popup = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                )
                popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
                logging.info("Всплывающее окно закрыто")
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
            self.login_attempts = 0
            return True
        except Exception as e:
            self.login_attempts += 1
            logging.error(f"Ошибка авторизации (попытка {self.login_attempts}): {e}")
            return False

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
                        f"💰 Новая продажа #{sale_data['number']}\n"
                        f"🏠 {sale_data['address']}\n"
                        f"⏰ {sale_data['time']} | ⚖️{sale_data['liters']}\n"
                        f"💵 {sale_data['total']} ({sale_data['payment']})"
                    )
        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")

    def get_payment_method(self, cell):
        """Определение метода оплаты"""
        try:
            icons = cell.find_elements(By.CSS_SELECTOR, "svg")
            if not icons:
                return "Неизвестно"
                
            icon_html = icons[0].get_attribute("outerHTML")
            
            if 'd="M336 32c-48.6 0-92.6 9-124.5 23.4' in icon_html:
                return "Монеты"
            elif 'd="M528 32H48C21.5 32 0 53.5 0 80v352c0 26.5' in icon_html:
                return "Банковская карта"
            elif 'd="M320 144c-53.02 0-96 50.14-96 112 0 61.85' in icon_html:
                return "Купюры"
            
            return "Неизвестно"
        except Exception as e:
            logging.warning(f"Ошибка определения метода оплаты: {e}")
            return "Неизвестно"

    def check_terminals(self):
        """Проверка состояния терминалов"""
        try:
            self.driver.get(urljoin(BASE_URL, 'terminals'))
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1"))
            )
            
            problem_terminals = self.driver.find_elements(By.CSS_SELECTOR, "tr._hasProblem_1gunj_20")
            for terminal in problem_terminals:
                try:
                    name = terminal.find_element(By.CSS_SELECTOR, "td:nth-child(2)").text.strip()
                    alerts_count = len(terminal.find_elements(By.CSS_SELECTOR, "span._error_irtpv_12"))
                    
                    if name not in self.last_problems or alerts_count > self.last_problems[name].get('count', 0):
                        self.send_notification(
                            f"⚠️ Проблема с терминалом: {name}\n"
                            f"Количество ошибок: {alerts_count}"
                        )
                        self.last_problems[name] = {
                            'count': alerts_count,
                            'last_check': datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                        
                except Exception as e:
                    logging.error(f"Ошибка обработки терминала: {e}")
                    
        except Exception as e:
            logging.error(f"Ошибка проверки терминалов: {e}")
            self.send_notification("🔴 Не удалось проверить состояние терминалов")

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
        try:
            logging.info("Запуск мониторинга AliveWater")
            
            if not self.login():
                self.send_notification("🔴 Ошибка авторизации!")
                return
            
            self.check_sales()
            self.check_terminals()
            
        except Exception as e:
            error_msg = f"🔴 Критическая ошибка: {str(e)[:200]}"
            logging.error(error_msg, exc_info=True)
            if ADMIN_CHAT_ID:
                bot.send_message(ADMIN_CHAT_ID, error_msg)
        finally:
            if self.driver:
                self.driver.quit()
            logging.info("Драйвер закрыт")

# Команды бота
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, 
        "👋 Привет! Я бот для мониторинга AliveWater.\n\n"
        "📋 Доступные команды:\n"
        "/subscribe - подписаться на уведомления\n"
        "/unsubscribe - отписаться от уведомлений\n"
        "/id - узнать свой chat_id\n\n"
        "Автоматические уведомления приходят каждые 5 минут."
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
        
        if cursor.rowcount > 0:
            reply = "✅ Вы успешно подписались на уведомления!"
            logging.info(f"Новый подписчик: {message.chat.id}")
        else:
            reply = "ℹ️ Вы уже подписаны на уведомления"
        
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка подписки: {e}")
        logging.error(f"Ошибка подписки: {e}")
    finally:
        conn.close()

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe(message):
    conn = sqlite3.connect('subscribers.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'DELETE FROM subscribers WHERE chat_id = ?',
            (message.chat.id,)
        )
        conn.commit()
        
        if cursor.rowcount > 0:
            reply = "✅ Вы отписались от уведомлений"
            logging.info(f"Отписался: {message.chat.id}")
        else:
            reply = "ℹ️ Вы не были подписаны"
        
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка отписки: {e}")
        logging.error(f"Ошибка отписки: {e}")
    finally:
        conn.close()

@bot.message_handler(commands=['id'])
def send_id(message):
    bot.reply_to(message, f"Ваш chat_id: `{message.chat.id}`", parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if ADMIN_CHAT_ID and str(message.chat.id) != ADMIN_CHAT_ID:
        return
        
    conn = sqlite3.connect('subscribers.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT COUNT(*) FROM subscribers')
        count = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT username, first_name, last_name, chat_id 
            FROM subscribers 
            ORDER BY subscribed_at DESC 
            LIMIT 10
        ''')
        last_subscribers = cursor.fetchall()
        
        stats_msg = f"📊 Всего подписчиков: {count}\n\n"
        stats_msg += "Последние 10 подписчиков:\n"
        
        for sub in last_subscribers:
            username, first_name, last_name, chat_id = sub
            name = f"{first_name or ''} {last_name or ''}".strip() or username or "Без имени"
            stats_msg += f"- {name} (`{chat_id}`)\n"
        
        bot.reply_to(message, stats_msg, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка получения статистики: {e}")
    finally:
        conn.close()

def run_bot():
    """Запуск бота в отдельном потоке"""
    try:
        bot.infinity_polling()
    except Exception as e:
        logging.error(f"Ошибка бота: {e}")

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запускаем мониторинг
    monitor = AliveWaterMonitor()
    monitor.run()
