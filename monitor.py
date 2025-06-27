
import os
import time
import logging
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

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
CHECK_INTERVAL = 60
MAX_WAIT = 30
MAX_LOGIN_ATTEMPTS = 3

bot = telebot.TeleBot(BOT_TOKEN)

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
        """Отправка уведомления в Telegram"""
        try:
            bot.send_message(CHAT_ID, message)
            logging.info(f"Уведомление отправлено: {message[:50]}...")
        except Exception as e:
            logging.error(f"Ошибка отправки уведомления: {e}")

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
            self.send_notification(f"🔴 Критическая ошибка: {str(e)[:200]}")
            logging.error(f"Критическая ошибка: {e}", exc_info=True)
        finally:
            if self.driver:
                self.driver.quit()
            logging.info("Драйвер закрыт")

if __name__ == '__main__':
    monitor = AliveWaterMonitor()
    monitor.run()
