
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

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')  # Ваш chat_id для ошибок
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
CHECK_INTERVAL = 300  # 5 минут между проверками

bot = telebot.TeleBot(BOT_TOKEN)

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.last_sale = None
        self.last_problems = {}
        self.setup_driver()

    def setup_driver(self):
        """Настройка Chrome WebDriver"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1200,800")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.implicitly_wait(10)

    def login(self):
        """Авторизация в системе"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            time.sleep(2)

            # Закрытие всплывающего окна
            try:
                popup = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                )
                popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary").click()
            except:
                pass

            # Ввод учетных данных
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            ).send_keys(LOGIN)
            
            self.driver.find_element(By.CSS_SELECTOR, "input[name='password']").send_keys(PASSWORD)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            # Проверка успешного входа
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span._container_iuuwv_1"))
            )
            return True
        except Exception as e:
            self.send_notification(f"🔴 Ошибка авторизации: {str(e)[:200]}")
            return False

    def check_sales(self):
        """Проверка новых продаж"""
        try:
            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, 30).until(
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
                        f"🏠 Адрес: {sale_data['address']}\n"
                        f"⏰ Время: {sale_data['time']}\n"
                        f"⚖️ Объем: {sale_data['liters']}\n"
                        f"💵 Сумма: {sale_data['total']}\n"
                        f"🔧 Способ оплаты: {sale_data['payment']}"
                    )
        except Exception as e:
            self.send_notification(f"🔴 Ошибка проверки продаж: {str(e)[:200]}")
            logging.error(f"Ошибка проверки продаж: {e}")

    def check_terminals(self):
        """Проверка состояния терминалов"""
        try:
            self.driver.get(urljoin(BASE_URL, 'terminals'))
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1"))
            )
            
            problem_terminals = self.driver.find_elements(By.CSS_SELECTOR, "tr._hasProblem_1gunj_20")
            for terminal in problem_terminals:
                try:
                    name = terminal.find_element(By.CSS_SELECTOR, "td:nth-child(2)").text.strip()
                    error_count = len(terminal.find_elements(By.CSS_SELECTOR, "span._error_irtpv_12"))
                    
                    if name not in self.last_problems or error_count > self.last_problems[name].get('count', 0):
                        self.send_notification(
                            f"⚠️ Проблема с терминалом: {name}\n"
                            f"🔴 Количество ошибок: {error_count}\n"
                            f"🔗 Ссылка: {urljoin(BASE_URL, 'terminals')}"
                        )
                        self.last_problems[name] = {
                            'count': error_count,
                            'last_check': datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                except Exception as e:
                    logging.error(f"Ошибка обработки терминала: {e}")
                    
        except Exception as e:
            self.send_notification(f"🔴 Ошибка проверки терминалов: {str(e)[:200]}")
            logging.error(f"Ошибка проверки терминалов: {e}")

    def send_notification(self, message):
        """Отправка уведомления"""
        try:
            bot.send_message(CHAT_ID, message)
            logging.info(f"Отправлено уведомление: {message[:50]}...")
        except Exception as e:
            logging.error(f"Ошибка отправки уведомления: {e}")

    def run(self):
        """Основной цикл мониторинга"""
        try:
            if not self.login():
                return
            
            self.check_sales()
            self.check_terminals()
            
        except Exception as e:
            self.send_notification(f"🔴 Критическая ошибка: {str(e)[:200]}")
            logging.error(f"Критическая ошибка: {e}")
        finally:
            self.driver.quit()
            logging.info("Драйвер закрыт")

if __name__ == '__main__':
    monitor = AliveWaterMonitor()
    monitor.run()
