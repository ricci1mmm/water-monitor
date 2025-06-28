
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
CHAT_ID = os.getenv('CHAT_ID')
BASE_URL = 'https://my.alivewater.cloud/'
LOGIN = os.getenv('LOGIN')
PASSWORD = os.getenv('PASSWORD')
MAX_WAIT = 30

bot = telebot.TeleBot(BOT_TOKEN)

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.last_sale = None
        self.last_problems = {}
        self.setup_driver()

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
        """Авторизация в системе с улучшенной обработкой"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            
            # Ожидание загрузки страницы
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Закрытие всплывающего окна (если есть)
            try:
                popup = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-modal-content"))
                )
                close_btn = popup.find_element(By.CSS_SELECTOR, "button.ant-btn-primary")
                self.driver.execute_script("arguments[0].click();", close_btn)
                logging.info("Всплывающее окно закрыто")
            except Exception as e:
                logging.info("Всплывающее окно не найдено")
            
            # Ввод учетных данных
            login_field = WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            )
            login_field.clear()
            login_field.send_keys(LOGIN)
            
            password_field = self.driver.find_element(By.CSS_SELECTOR, "input[name='password']")
            password_field.clear()
            password_field.send_keys(PASSWORD)
            
            # Нажатие кнопки входа
            submit_btn = WebDriverWait(self.driver, MAX_WAIT).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            submit_btn.click()
            
            # Проверка успешного входа
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


    def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_purchase": None}

def save_data(last_purchase):
    with open(DATA_FILE, 'w') as f:
        json.dump({"last_purchase": last_purchase}, f)

def main():
    while True:
        data = load_data()
        last_purchase = data["last_purchase"]

        if last_purchase:
            print(f"Последняя покупка: {last_purchase}")
        else:
            print("У вас еще не было покупок воды.")

        print("\n1 - Новая покупка воды")
        print("2 - Выход")

        choice = input("\nВыберите действие: ").strip()

        if choice == "1":
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_data(now)
            print(f"Покупка воды зарегистрирована: {now}")

            # Отправка уведомления в Telegram
            options = Options()
            options.add_argument('--headless')
            driver = webdriver.Chrome(options=options)
            driver.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}&text=Купил воду {now}")
            time.sleep(3)
            driver.quit()

        elif choice == "2":
            print("Выход из программы.")
            break

        else:
            print("Ошибка: выберите 1 или 2")

    
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
                        f"💳 Способ оплаты: {sale_data['payment']}"
                    )
        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")
            self.send_notification(f"🔴 Ошибка проверки продаж: {str(e)[:200]}")

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
