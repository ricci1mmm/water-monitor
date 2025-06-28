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
POLL_INTERVAL = 300  # 5 минут между проверками
DATA_FILE = 'water_monitor_state.json'

bot = telebot.TeleBot(BOT_TOKEN)

class AliveWaterMonitor:
    def __init__(self):
        self.driver = None
        self.state = self.load_state()
        self.setup_driver()
        self.is_running = True

    def load_state(self):
        """Загрузка состояния из файла"""
        try:
            with open(DATA_FILE, 'r') as f:
                state = json.load(f)
                # Конвертация старого формата
                if 'last_problems' not in state:
                    state['last_problems'] = {}
                return state
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'last_sale_id': None,  # Изменено на ID последней продажи
                'last_problems': {},
                'last_check': None,
                'known_terminals': {}
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
        """Авторизация в системе с улучшенной обработкой"""
        try:
            self.driver.get(urljoin(BASE_URL, 'login'))
            
            # Ожидание загрузки страницы
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Закрытие всплывающих окон
            self.close_popups()
            
            # Ввод учетных данных
            login_field = WebDriverWait(self.driver, MAX_WAIT).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='login']"))
            )
            login_field.clear()
            login_field.send_keys(LOGIN)
            
            password_field = self.driver.find_element(By.CSS_SELECTOR, "input[name='password']")
            password_field.clear()
            password_field.send_keys(PASSWORD)
            
            # Нажатие кнопки входа через JavaScript
            submit_btn = WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button[type='submit']"))
            )
            self.driver.execute_script("arguments[0].click();", submit_btn)
            
            # Проверка успешного входа
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.dashboard, div._container_iuuwv_1"))
            )
            logging.info("Авторизация успешна")
            return True
            
        except Exception as e:
            logging.error(f"Ошибка авторизации: {e}")
            self.send_notification(f"🔴 Ошибка авторизации: {str(e)[:200]}")
            return False

    def close_popups(self):
        """Закрытие всевозможных всплывающих окон"""
        try:
            # Попробуем закрыть разные типы попапов
            for _ in range(3):  # Несколько попыток
                try:
                    # Стандартные модальные окна
                    popups = self.driver.find_elements(By.CSS_SELECTOR, "div.ant-modal-content")
                    for popup in popups:
                        try:
                            close_btn = popup.find_element(By.CSS_SELECTOR, "button.ant-modal-close")
                            if close_btn.is_displayed():
                                self.driver.execute_script("arguments[0].click();", close_btn)
                                logging.info("Модальное окно закрыто")
                                time.sleep(1)
                        except:
                            continue
                    
                    # Куки-баннеры
                    cookie_banners = self.driver.find_elements(By.CSS_SELECTOR, "div.cookie-banner, div.cookie-notice")
                    for banner in cookie_banners:
                        try:
                            accept_btn = banner.find_element(By.CSS_SELECTOR, "button.accept-cookies, button#cookie-ok")
                            if accept_btn.is_displayed():
                                self.driver.execute_script("arguments[0].click();", accept_btn)
                                logging.info("Cookie-баннер закрыт")
                                time.sleep(0.5)
                        except:
                            continue
                    
                    # Через JavaScript на всякий случай
                    self.driver.execute_script("""
                        const closeElements = document.querySelectorAll(
                            'div[aria-label="Close"], button.ant-modal-close, div.cookie-banner button'
                        );
                        closeElements.forEach(el => {
                            try {
                                if (el.offsetParent !== null) el.click();
                            } catch(e) {}
                        });
                        
                        // Удаление фонов
                        const masks = document.querySelectorAll('div.ant-modal-mask, div.modal-backdrop');
                        masks.forEach(mask => mask.remove());
                    """)
                except Exception as e:
                    logging.debug(f"Ошибка при закрытии попапов: {e}")
                
                time.sleep(1)
        except Exception as e:
            logging.warning(f"Общая ошибка закрытия попапов: {e}")

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
        """Проверка новых продаж с корректной обработкой"""
        try:
            self.driver.get(urljoin(BASE_URL, 'sales'))
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1"))
            )
            
            time.sleep(3)  # Ожидание загрузки данных
            self.close_popups()
            
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table._table_1s08q_1 tbody tr")
            if not rows:
                logging.info("Нет данных о продажах")
                return

            new_sales = []
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 6:
                        continue
                        
                    sale_id = cells[0].text.strip()
                    
                    # Если дошли до последней известной продажи - остановка
                    if sale_id == self.state.get('last_sale_id'):
                        break
                        
                    sale_data = {
                        'id': sale_id,
                        'address': cells[1].text.strip(),
                        'time': cells[2].text.strip(),
                        'liters': cells[3].text.strip(),
                        'total': cells[4].text.strip(),
                        'payment': self.get_payment_method(cells[5])
                    }
                    new_sales.append(sale_data)
                except Exception as e:
                    logging.warning(f"Ошибка обработки строки продажи: {e}")

            # Обработка новых продаж в обратном порядке
            for sale in reversed(new_sales):
                self.send_notification(
                    f"💰 Новая продажа #{sale['id']}\n"
                    f"🏠 Адрес: {sale['address']}\n"
                    f"⏰ Время: {sale['time']}\n"
                    f"⚖️ Объем: {sale['liters']}\n"
                    f"💵 Сумма: {sale['total']}\n"
                    f"💳 Способ оплаты: {sale['payment']}"
                )
                logging.info(f"Обнаружена новая продажа: {sale['id']}")

            # Обновление состояния
            if new_sales:
                self.state['last_sale_id'] = new_sales[0]['id']  # ID самой новой продажи
                self.save_state()

        except Exception as e:
            logging.error(f"Ошибка проверки продаж: {e}")
            self.send_notification(f"🔴 Ошибка проверки продаж: {str(e)[:200]}")

    def check_terminals(self):
        """Проверка состояния терминалов"""
        try:
            self.driver.get(urljoin(BASE_URL, 'terminals'))
            WebDriverWait(self.driver, MAX_WAIT).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "table._table_1s08q_1"))
            )
            
            time.sleep(3)  # Ожидание загрузки данных
            self.close_popups()
            
            current_problems = {}
            rows = self.driver.find_elements(By.CSS_SELECTOR, "tr._hasProblem_1gunj_20")
            
            for terminal in rows:
                try:
                    name = terminal.find_element(By.CSS_SELECTOR, "td:nth-child(2)").text.strip()
                    error_count = len(terminal.find_elements(By.CSS_SELECTOR, "span._error_irtpv_12"))
                    current_problems[name] = error_count
                except Exception as e:
                    logging.error(f"Ошибка обработки терминала: {e}")

            # Проверка изменений состояния
            last_problems = self.state.get('last_problems', {})
            
            # Новые проблемы
            for name, count in current_problems.items():
                if name not in last_problems or last_problems[name] < count:
                    self.send_notification(
                        f"⚠️ Проблема с терминалом: {name}\n"
                        f"🔴 Количество ошибок: {count}\n"
                        f"🔗 Ссылка: {urljoin(BASE_URL, 'terminals')}"
                    )
            
            # Восстановленные терминалы
            for name in list(last_problems.keys()):
                if name not in current_problems:
                    self.send_notification(
                        f"✅ Терминал восстановлен: {name}\n"
                        f"🟢 Проблемы устранены\n"
                        f"🔗 Ссылка: {urljoin(BASE_URL, 'terminals')}"
                    )
            
            # Обновление состояния
            self.state['last_problems'] = current_problems
            self.save_state()
                    
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

    def run_monitoring(self):
        """Основной цикл мониторинга"""
        logging.info("Запуск постоянного мониторинга AliveWater")
        
        while self.is_running:
            try:
                # Переинициализация драйвера при необходимости
                if not self.driver:
                    self.setup_driver()
                
                # Авторизация
                if not self.login():
                    time.sleep(60)
                    continue
                
                # Проверка продаж
                self.check_sales()
                
                # Проверка терминалов
                self.check_terminals()
                
                # Обновление времени последней проверки
                self.state['last_check'] = datetime.now().isoformat()
                self.save_state()
                
                # Пауза между проверками
                logging.info(f"Очередная проверка завершена. Ожидание {POLL_INTERVAL} сек.")
                time.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logging.error(f"Критическая ошибка: {e}")
                self.send_notification(f"🔴 Критическая ошибка мониторинга: {str(e)[:200]}")
                
                # Перезапуск драйвера при ошибках
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
                    time.sleep(10)

    def stop(self):
        """Остановка мониторинга"""
        self.is_running = False
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

if __name__ == '__main__':
    monitor = AliveWaterMonitor()
    try:
        monitor.run_monitoring()
    except KeyboardInterrupt:
        monitor.stop()
        logging.info("Мониторинг остановлен по запросу пользователя")
    except Exception as e:
        monitor.stop()
        logging.error(f"Необработанное исключение: {e}")
