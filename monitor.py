import os
import time
import json
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
CHAT_ID = os.getenv('CHAT_ID')
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
MAX_WAIT = 30
DATA_FILE = 'water_monitor_state.json'

bot = telebot.TeleBot(BOT_TOKEN)

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.state = self.load_state()
        self.setup_driver()

    def load_state(self):
        """Загрузка состояния из файла"""
        try:
            with open(DATA_FILE, 'r') as f:
                state = json.load(f)
                # Проверяем структуру файла
                if 'last_sale' not in state:
                    state['last_sale'] = None
                if 'last_problems' not in state:
                    state['last_problems'] = {}
                if 'last_check' not in state:
                    state['last_check'] = None
                return state
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'last_sale': None,
                'last_problems': {},
                'last_check': None
            }

    def save_state(self):
        """Сохранение состояния в файл"""
        with open(DATA_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def setup_driver(self):
        """Настройка Chrome WebDriver"""
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
            
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            try:
                popup = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                )
                close_btn = popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary")
                self.driver.execute_script("arguments[0].click();", close_btn)
                logging.info("Всплывающее окно закрыто")
            except Exception:
                logging.info("Всплывающее окно не найдено")
            
            login_field = WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            )
            login_field.clear()
            login_field.send_keys(LOGIN)
            
            password_field = self.driver.find_element(By.CSS_SELECTOR, "input[name='password']")
            password_field.clear()
            password_field.send_keys(PASSWORD)
            
            submit_btn = WebDriverWait(self.driver, MAX_WAIT).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            submit_btn.click()
            
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span._container_iuuwv_1"))
            )
            logging.info("Авторизация успешна")
            return True
            
        except Exception as e:
            logging.error(f"Ошибка авторизации: {e}")
            self.send_notification(f"🔴 Ошибка авторизации: {str(e)[:200]}")
            return False

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

    def check_sales(self):
        """Проверка новых продаж"""
        try:
            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1"))
            )
            
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr")
            if not rows:
                logging.info("Нет данных о продажах")
                return

            # Получаем все продажи на странице
            current_sales = []
            for row in rows[:5]:  # Проверяем только последние 5 продаж
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 6:
                        sale_data = {
                            'number': cells[0].text.strip(),
                            'address': cells[1].text.strip(),
                            'time': cells[2].text.strip(),
                            'liters': cells[3].text.strip(),
                            'total': cells[4].text.strip(),
                            'payment': self.get_payment_method(cells[5]),
                            'timestamp': datetime.now().isoformat()
                        }
                        current_sales.append(sale_data)
                except Exception as e:
                    logging.error(f"Ошибка обработки строки продажи: {e}")

            if not current_sales:
                logging.info("Не удалось получить данные о продажах")
                return

            # Проверяем, есть ли новые продажи
            if self.state['last_sale']:
                last_sale_number = self.state['last_sale']['number']
                new_sales = [sale for sale in current_sales if sale['number'] != last_sale_number]
            else:
                new_sales = current_sales[:1]  # Берем только последнюю, если это первый запуск

            # Если есть новые продажи, обрабатываем их от новых к старым
            if new_sales:
                # Сортируем по номеру (предполагая, что чем больше номер, тем новее продажа)
                new_sales_sorted = sorted(new_sales, key=lambda x: int(x['number']), reverse=True)
                
                for sale in new_sales_sorted:
                    # Проверяем, не была ли уже обработана эта продажа
                    if not self.state['last_sale'] or sale['number'] != self.state['last_sale']['number']:
                        self.send_sale_notification(sale)
                        self.state['last_sale'] = sale
                        self.save_state()
                        break  # Отправляем только самую новую продажу

        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")
            self.send_notification(f"🔴 Ошибка проверки продаж: {str(e)[:200]}")

    def send_sale_notification(self, sale_data):
        """Отправка уведомления о продаже"""
        message = (
            f"💰 Новая продажа #{sale_data['number']}\n"
            f"🏠 Адрес: {sale_data['address']}\n"
            f"⏰ Время: {sale_data['time']}\n"
            f"⚖️ Объем: {sale_data['liters']}\n"
            f"💵 Сумма: {sale_data['total']}\n"
            f"💳 Способ оплаты: {sale_data['payment']}"
        )
        self.send_notification(message)

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
                    error_count = len(terminal.find_elements(By.CSS_SELECTOR, "span._error_irtpv_12"))
                    
                    if (name not in self.state['last_problems'] or 
                        error_count > self.state['last_problems'][name].get('count', 0)):
                        self.send_notification(
                            f"⚠️ Проблема с терминалом: {name}\n"
                            f"🔴 Количество ошибок: {error_count}\n"
                            f"🔗 Ссылка: {urljoin(BASE_URL, 'terminals')}"
                        )
                        self.state['last_problems'][name] = {
                            'count': error_count,
                            'last_check': datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                        self.save_state()
                except Exception as e:
                    logging.error(f"Ошибка обработки терминала: {e}")
                    
        except Exception as e:
            logging.error(f"Ошибка проверки терминалов: {e}")
            self.send_notification("🔴 Не удалось проверить состояние терминалов")

    def send_notification(self, message):
        """Отправка уведомления"""
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
                return
            
            self.check_sales()
            self.check_terminals()
            
        except Exception as e:
            logging.error(f"Критическая ошибка: {e}")
            self.send_notification(f"🔴 Критическая ошибка мониторинга: {str(e)[:200]}")
        finally:
            if self.driver:
                self.driver.quit()
                logging.info("Драйвер закрыт")

if __name__ == '__main__':
    monitor = AliveWaterMonitor()
    monitor.run()
