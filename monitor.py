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
        self.driver = None
        self.last_sale = None
        self.setup_driver()

    def setup_driver(self):
        """Настройка ChromeDriver с улучшенными параметрами"""
        try:
            options = Options()
            
            # Критически важные параметры для работы в headless
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            
            # Попробуем сначала без headless для диагностики
            # options.add_argument("--headless=new")
            
            # Настройки для обхода защиты
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            
            # Изменяем свойство navigator.webdriver
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            self.driver.set_page_load_timeout(30)
            return True
        except Exception as e:
            logging.error(f"Ошибка инициализации драйвера: {e}")
            return False

    def login(self):
        """Улучшенная авторизация с обработкой различных сценариев"""
        try:
            logging.info("Попытка авторизации на сайте...")
            self.driver.get(urljoin(BASE_URL, 'login'))
            
            # Явное ожидание появления формы
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "form"))
            )
            
            # Ввод логина
            login_field = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='login']"))
            )
            login_field.clear()
            login_field.send_keys(LOGIN)
            
            # Ввод пароля
            password_field = self.driver.find_element(By.CSS_SELECTOR, "input[name='password']")
            password_field.clear()
            password_field.send_keys(PASSWORD)
            
            # Клик по кнопке входа
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()
            
            # Ожидание успешного входа (адаптивный вариант)
            WebDriverWait(self.driver, 20).until(
                lambda d: "dashboard" in d.current_url or 
                         any(text in d.page_source for text in ["Добро пожаловать", "Welcome"])
            )
            
            logging.info("Авторизация успешна")
            return True
            
        except Exception as e:
            logging.error(f"Ошибка авторизации: {str(e)[:200]}")
            
            # Сохраняем скриншот для диагностики
            try:
                self.driver.save_screenshot("login_error.png")
                logging.info("Скриншот ошибки сохранен в login_error.png")
            except:
                pass
            
            return False

    def check_sales(self):
        """Проверка новых продаж"""
        try:
            if not self.login():
                logging.error("Не удалось авторизоваться, пропускаем проверку")
                return

            logging.info("Переход на страницу продаж...")
            self.driver.get(urljoin(BASE_URL, 'sales'))
            
            # Ожидание загрузки таблицы
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
            )
            
            # Поиск последней продажи
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            if not rows:
                logging.info("Таблица продаж пуста")
                return

            first_row = rows[0]
            cells = first_row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 6:
                logging.warning("Неожиданное количество столбцов в таблице")
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
            try:
                self.driver.save_screenshot("sales_error.png")
            except:
                pass

    def get_payment_type(self, cell):
        """Определение типа оплаты"""
        try:
            # Попробуем определить по классам
            class_list = cell.get_attribute("class")
            if 'coin' in class_list.lower():
                return "🪙 Монеты"
            elif 'bill' in class_list.lower():
                return "💵 Купюры"
            elif 'card' in class_list.lower():
                return "💳 Карта"
            
            # Альтернативный вариант по иконкам
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
        """Отправка уведомления"""
        message = (
            f"💰 <b>Новая продажа #{sale_data['number']}</b>\n"
            f"🏠 {sale_data['address']}\n"
            f"⏰ {sale_data['time']} | ⚖️ {sale_data['liters']}л\n"
            f"💵 {sale_data['total']}\n"
            f"🔹 {sale_data['payment']}"
        )
        
        try:
            conn = sqlite3.connect('subscribers.db')
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM subscribers")
            for (chat_id,) in cursor.fetchall():
                try:
                    bot.send_message(chat_id, message)
                    logging.info(f"Уведомление отправлено в чат {chat_id}")
                except Exception as e:
                    logging.error(f"Ошибка отправки: {e}")
        except Exception as e:
            logging.error(f"Ошибка работы с БД: {e}")
        finally:
            conn.close()

def run_monitor():
    """Основной цикл мониторинга"""
    monitor = WaterMonitor()
    while True:
        try:
            monitor.check_sales()
            time.sleep(60)  # Проверка каждую минуту
        except Exception as e:
            logging.error(f"Критическая ошибка: {e}")
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
