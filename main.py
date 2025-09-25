import os
import json
import time
import requests
import base64
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from openai import OpenAI


# 自定义等待条件：等待元素出现且其 src 属性不为空
class wait_for_image_src(object):
    def __init__(self, locator):
        self.locator = locator

    def __call__(self, driver):
        try:
            element = EC.visibility_of_element_located(self.locator)(driver)
            if element and element.get_attribute('src'):
                return element
            else:
                return False
        except NoSuchElementException:
            return False


class AutoClassBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("长江雨课堂自动助手")
        self.root.geometry("600x600")

        # 配置文件路径
        self.config_file = "config.json"
        self.settings = self.load_settings()

        self.is_running = False
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()

        # 全局驱动实例
        self.driver = None

        self.setup_ui()
        self.start_log_processor()
        self.log_message("应用已启动。")
        self.log_message("请先在'设置'中获取登录cookies并保存配置。")
        self.update_cookie_info()

    def setup_ui(self):
        # 创建 Notebook (Tabbed interface)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        # 主页
        self.home_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.home_frame, text="主页")
        self.setup_home_ui()

        # 设置页
        self.settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_frame, text="设置")
        self.setup_settings_ui()

    def setup_home_ui(self):
        # 顶部控制区
        control_frame = ttk.Frame(self.home_frame, padding="10")
        control_frame.pack(fill="x")

        self.status_label = ttk.Label(control_frame, text="当前状态: 停止", font=("Helvetica", 12))
        self.status_label.pack(side="left", padx=(0, 20))

        self.toggle_button = ttk.Button(control_frame, text="启动自动答题", command=self.toggle_bot)
        self.toggle_button.pack(side="left")

        # Cookies 有效期显示
        self.cookie_status_label = ttk.Label(control_frame, text="Cookies有效期: 未知", font=("Helvetica", 10),
                                             foreground="gray")
        self.cookie_status_label.pack(side="right")

        # 日志区域
        log_frame = ttk.Frame(self.home_frame, padding="10")
        log_frame.pack(expand=True, fill="both")

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='disabled', font=("Monospaced", 10))
        self.log_text.pack(expand=True, fill="both")

    def setup_settings_ui(self):
        settings_frame = ttk.Frame(self.settings_frame, padding="10")
        settings_frame.pack(expand=True, fill="both")

        # helper function to create rows
        def create_setting_row(parent, label_text, widget_class, default_value=None, options=None):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=5)
            label = ttk.Label(row, text=label_text, width=20)
            label.pack(side="left")

            if widget_class == ttk.Combobox:
                var = tk.StringVar(value=default_value)
                widget = widget_class(row, textvariable=var, values=options)
                widget.pack(side="left", fill="x", expand=True)
            elif widget_class == ttk.Checkbutton:
                var = tk.BooleanVar(value=default_value)
                widget = widget_class(row, variable=var, text="")
                widget.pack(side="left", fill="x", expand=True)
            else:
                var = tk.StringVar(value=default_value)
                widget = widget_class(row, textvariable=var)
                widget.pack(side="left", fill="x", expand=True)
            return var, widget

        # 设置项
        self.start_time_var, _ = create_setting_row(settings_frame, "每日开始时间 (HH:MM):", ttk.Entry,
                                                    self.settings.get("start_time", "07:00"))
        self.end_time_var, _ = create_setting_row(settings_frame, "每日结束时间 (HH:MM):", ttk.Entry,
                                                  self.settings.get("end_time", "22:00"))

        # 新增无头模式选项
        self.headless_var, _ = create_setting_row(settings_frame, "静默运行 (无头模式):", ttk.Checkbutton,
                                                  self.settings.get("headless_mode", False))

        self.ai_model_var, self.ai_model_combobox = create_setting_row(settings_frame, "AI模型选择:", ttk.Combobox,
                                                                       self.settings.get("ai_model", "豆包AI"),
                                                                       options=["豆包AI", "Gemini AI"])

        self.doubao_key_var, _ = create_setting_row(settings_frame, "豆包AI API Key:", ttk.Entry,
                                                    self.settings.get("doubao_api_key", ""))
        self.gemini_key_var, _ = create_setting_row(settings_frame, "Gemini AI API Key:", ttk.Entry,
                                                    self.settings.get("gemini_api_key", ""))

        self.submit_delay_var, _ = create_setting_row(settings_frame, "提交答案等待时间 (秒):", ttk.Entry,
                                                      self.settings.get("submit_delay", "5"))
        self.check_interval_var, _ = create_setting_row(settings_frame, "检查/刷新间隔 (秒):", ttk.Entry,
                                                        self.settings.get("check_interval", "60"))

        # 新增题目刷新间隔设置
        self.quiz_refresh_interval_var, _ = create_setting_row(settings_frame, "答题刷新间隔 (秒):", ttk.Entry,
                                                               self.settings.get("quiz_refresh_interval", "10"))

        self.xxtui_key_var, _ = create_setting_row(settings_frame, "微信提醒API Key:", ttk.Entry,
                                                   self.settings.get("xxtui_api_key", ""))

        # 按钮
        button_frame = ttk.Frame(settings_frame)
        button_frame.pack(fill="x", pady=20)

        save_button = ttk.Button(button_frame, text="保存设置", command=self.save_settings)
        save_button.pack(side="left", padx=(0, 10))

        get_cookies_button = ttk.Button(button_frame, text="获取登录Cookies", command=self.run_get_cookies_thread)
        get_cookies_button.pack(side="left", padx=(0, 10))

    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                messagebox.showerror("错误", "配置文件格式错误，将重置为默认设置。")
                os.remove(self.config_file)
        return {
            "start_time": "07:00",
            "end_time": "22:00",
            "headless_mode": False,
            "ai_model": "豆包AI",
            "doubao_api_key": "",
            "gemini_api_key": "",
            "submit_delay": 5,
            "check_interval": 60,
            "quiz_refresh_interval": 10,
            "xxtui_api_key": "",
            "last_cookie_warn_date": ""
        }

    def save_settings(self):
        try:
            settings = {
                "start_time": self.start_time_var.get(),
                "end_time": self.end_time_var.get(),
                "headless_mode": self.headless_var.get(),
                "ai_model": self.ai_model_var.get(),
                "doubao_api_key": self.doubao_key_var.get(),
                "gemini_api_key": self.gemini_key_var.get(),
                "submit_delay": int(self.submit_delay_var.get()),
                "check_interval": int(self.check_interval_var.get()),
                "quiz_refresh_interval": int(self.quiz_refresh_interval_var.get()),
                "xxtui_api_key": self.xxtui_key_var.get(),
                "last_cookie_warn_date": self.settings.get("last_cookie_warn_date", "")
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            self.settings = settings
            self.log_message("设置已成功保存。")
        except ValueError:
            messagebox.showerror("错误", "提交等待时间、检查间隔或答题刷新间隔必须是数字。")
            self.log_message("错误：保存设置失败。")

    def run_get_cookies_thread(self):
        thread = threading.Thread(target=self.get_cookies, daemon=True)
        thread.start()

    def get_cookies(self):
        """获取登录Cookies并保存，复用已启动的驱动"""
        self.log_message("开始获取Cookies，请在弹出的浏览器窗口中完成登录...")
        if not self._start_driver():
            return

        driver = self.driver
        driver.get('https://changjiang.yuketang.cn')

        try:
            WebDriverWait(driver, 120).until(EC.presence_of_element_located((By.ID, 'tab-student')))
            cookies = driver.get_cookies()
            with open("cookies.txt", "w") as f1:
                f1.write(json.dumps(cookies))
            self.log_message("Cookies 已成功保存。")
            self.update_cookie_info()
        except TimeoutException:
            self.log_message("获取Cookies超时，请重新尝试。")
        finally:
            # 不在这里关闭 driver，让它保持开启
            pass

    def update_cookie_info(self):
        if os.path.exists("cookies.txt"):
            with open("cookies.txt", "r") as f:
                cookies = json.loads(f.read())

            latest_expiry = 0
            for cookie in cookies:
                if 'expiry' in cookie:
                    latest_expiry = max(latest_expiry, cookie['expiry'])

            if latest_expiry > 0:
                remaining_seconds = latest_expiry - time.time()
                if remaining_seconds > 0:
                    remaining_days = remaining_seconds / (60 * 60 * 24)
                    self.cookie_status_label.config(text=f"Cookies有效期: 约{remaining_days:.1f}天")
                else:
                    self.cookie_status_label.config(text="Cookies有效期: 已过期", foreground="red")
            else:
                self.cookie_status_label.config(text="Cookies有效期: 未知 (无过期信息)")
        else:
            self.cookie_status_label.config(text="Cookies有效期: 未找到 cookies.txt", foreground="orange")

    def check_cookie_expiry_and_notify(self):
        if not os.path.exists("cookies.txt"):
            return

        with open("cookies.txt", "r") as f:
            cookies = json.loads(f.read())

        latest_expiry = 0
        for cookie in cookies:
            if 'expiry' in cookie:
                latest_expiry = max(latest_expiry, cookie['expiry'])

        if latest_expiry > 0:
            remaining_seconds = latest_expiry - time.time()
            remaining_days = remaining_seconds / (60 * 60 * 24)

            now = datetime.now()
            last_warn_date = self.settings.get("last_cookie_warn_date", "")

            # 如果有效期小于等于3天，且当前时间是8点左右，且今天未发送过提醒
            if remaining_days <= 3 and now.hour == 8 and now.strftime("%Y-%m-%d") != last_warn_date:
                title = "长江雨课堂助手：Cookies即将过期"
                content = f"您的登录Cookies还剩约{remaining_days:.1f}天过期。请尽快在设置页面重新获取Cookies。"
                self.log_message(f"Cookies有效期不足3天，正在发送微信提醒。")
                self.send_wechat_notification(title, content)
                self.settings["last_cookie_warn_date"] = now.strftime("%Y-%m-%d")
                self.save_settings()  # 保存新的提醒日期

    def log_message(self, message):
        self.log_queue.put(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

    def start_log_processor(self):
        def process_queue():
            try:
                while True:
                    message = self.log_queue.get_nowait()
                    self.log_text.configure(state='normal')
                    self.log_text.insert(tk.END, message)
                    self.log_text.see(tk.END)
                    self.log_text.configure(state='disabled')
            except queue.Empty:
                pass
            self.root.after(100, process_queue)

        self.root.after(100, process_queue)

    def _start_driver(self):
        """初始化 Selenium 驱动，如果它尚未启动。"""
        if self.driver is None or not self.driver.service.is_connectable():
            self.log_message("正在启动浏览器...")
            chrome_options = Options()
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            if self.settings.get("headless_mode", False):
                chrome_options.add_argument('--headless=new')

            try:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                self.log_message("浏览器已启动。")
            except Exception as e:
                self.log_message(f"启动浏览器失败：{e}")
                self.driver = None
                return False
        return True

    def _stop_driver(self):
        """安全地关闭 Selenium 驱动。"""
        if self.driver:
            self.log_message("正在关闭浏览器...")
            self.driver.quit()
            self.driver = None
            self.log_message("浏览器已关闭。")

    def toggle_bot(self):
        if not self.is_running:
            if not self._start_driver():
                self.log_message("浏览器启动失败，无法开始自动答题。")
                return

            self.is_running = True
            self.stop_event.clear()
            self.toggle_button.config(text="停止自动答题")
            self.status_label.config(text="当前状态: 运行中")
            self.log_message("开始检查课程...")

            bot_thread = threading.Thread(target=self.run_bot_loop, daemon=True)
            bot_thread.start()
        else:
            self.is_running = False
            self.stop_event.set()
            self.toggle_button.config(text="启动自动答题")
            self.status_label.config(text="当前状态: 停止")
            self.log_message("自动答题已停止。")
            self._stop_driver()

    def run_bot_loop(self):
        try:
            while not self.stop_event.is_set():
                current_time = time.strftime("%H:%M", time.localtime())
                start_time_str = self.settings.get("start_time", "07:00")
                end_time_str = self.settings.get("end_time", "22:00")

                # 检查Cookies有效期并发送提醒
                self.check_cookie_expiry_and_notify()

                if start_time_str <= current_time <= end_time_str:
                    self.log_message("正在检查是否有正在进行的课程...")
                    self.get_into_class(self.driver)
                else:
                    self.log_message(f"当前时间不在设置的检查时间段内 ({start_time_str} - {end_time_str})，跳过检查。")

                # 等待设定的检查间隔
                self.update_cookie_info()
                self.stop_event.wait(int(self.settings.get("check_interval", 60)))

        except Exception as e:
            self.log_message(f"发生意外错误：{e}")
            # 发生错误时安全地停止 bot 并更新 UI
            self.root.after(0, self.toggle_bot)

    def get_into_class(self, driver):
        now_time = time.strftime("%H:%M", time.localtime())

        # 移除driver初始化代码，直接使用传入的driver
        driver.get('https://changjiang.yuketang.cn')

        if not os.path.exists("cookies.txt"):
            self.log_message("未找到 cookies.txt，请先在'设置'中获取。")
            return False

        with open("cookies.txt", "r") as f2:
            cookies = json.loads(f2.read())
        for cook in cookies:
            driver.add_cookie(cook)
        driver.refresh()

        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
            self.log_message("等待加载条消失...")
            WebDriverWait(driver, 3).until(
                EC.invisibility_of_element_located((By.XPATH, '//*[contains(@class, "jump_lesson__bar")]'))
            )

        except (TimeoutException, ElementNotInteractableException):
            self.log_message("未能点击学生标签，尝试直接寻找正在进行的课程...")

        try:
            self.log_message("正在检查是否有正在进行的课程...")
            class_element_xpath = '//*[contains(@class, "onlesson")]'
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, class_element_xpath)))
            driver.find_element(By.XPATH, class_element_xpath).click()

            # 引用新的变量，用于日志提示
            quiz_refresh_interval = int(self.settings.get("quiz_refresh_interval", 10))
            self.log_message(f"我去上课啦！我将会每{quiz_refresh_interval}秒检测一次随堂测试和签到，直到下课。")
            driver.switch_to.window(driver.window_handles[-1])

            while not self.stop_event.is_set():
                if driver.find_elements(By.XPATH, '//div[@title="下课啦！" and contains(@class, "timeline__msg")]'):
                    self.log_message("检测到下课啦！自动答题已停止。")
                    break

                self.check_and_sign_in(driver)
                self.answer(driver)
                # 使用新的设置值
                self.stop_event.wait(quiz_refresh_interval)

        except TimeoutException:
            self.log_message("你现在没课。")
        except Exception as e:
            self.log_message(f"发生意外错误：{e}")
        finally:
            self.log_message("检查课程流程结束。")
            return False

    def send_wechat_notification(self, title, content):
        xxtui_key = self.settings.get("xxtui_api_key")
        if not xxtui_key:
            self.log_message("警告！未设置微信提醒API Key，通知功能已禁用。")
            return

        api_url = f"https://www.xxtui.com/xxtui/{xxtui_key}"
        headers = {'Content-Type': 'application/json'}
        data = {"from": "课堂机器人", "title": title, "content": content, "channel": "WX_MP"}

        self.log_message("正在向xxtui发送通知。")
        try:
            response = requests.post(api_url, headers=headers, json=data, timeout=5)
            response.raise_for_status()
            result = response.json()
            if result.get('code') == 0:
                self.log_message("微信通知发送成功。")
            else:
                self.log_message(f"微信通知发送失败，错误码：{result.get('code')}，信息：{result.get('message')}")
        except requests.exceptions.RequestException as e:
            self.log_message(f"发送微信通知时发生错误：{e}")

    def get_ai_answer(self, image_url, question_type="objective"):
        """
        根据配置的模型调用AI并返回答案
        question_type: 'objective' 或 'subjective'
        """
        model = self.settings.get("ai_model", "豆包AI")
        prompt = ""
        if question_type == "objective":
            prompt = "看这张图片，请找出图中的习题。如果是单选题，请只返回一个选项字母（如 A）。如果是多选题，请返回所有正确选项的字母，并用逗号分隔（如 A,B,C）。如果无法确定，请返回 'C'。"
        elif question_type == "subjective":
            prompt = "看这张图片，请帮我解答这道主观题。请直接给出你的答案，不要包含任何额外的解释或格式。"

        # 下载图片
        try:
            image_response = requests.get(image_url, timeout=10)
            image_response.raise_for_status()
            image_bytes = image_response.content
        except requests.exceptions.RequestException as e:
            self.log_message(f"下载题目图片失败：{e}")
            return "图片下载失败，无法获取答案。"

        if model == "豆包AI":
            doubao_key = self.settings.get("doubao_api_key")
            if not doubao_key:
                return "未设置豆包AI API Key，无法获取答案。"

            try:
                client = OpenAI(
                    base_url="https://ark.cn-beijing.volces.com/api/v3",
                    api_key=doubao_key,
                )
                response = client.chat.completions.create(
                    model="doubao-seed-1-6-250615",
                    messages=[
                        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}},
                                                     {"type": "text", "text": prompt}]}
                    ], timeout=8
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                self.log_message(f"调用豆包AI API失败或超时：{e}")
                return "豆包AI调用失败。"

        elif model == "Gemini AI":
            gemini_key = self.settings.get("gemini_api_key")
            if not gemini_key:
                return "未设置Gemini AI API Key，无法获取答案。"

            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={gemini_key}"
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            payload = {"contents": [
                {"parts": [{"text": prompt}, {"inlineData": {"mimeType": "image/jpeg", "data": base64_image}}]}]}

            try:
                response = requests.post(api_url, json=payload, timeout=15)
                response.raise_for_status()
                result = response.json()
                candidate = result.get('candidates', [{}])[0]
                return candidate.get('content', {}).get('parts', [{}])[0].get('text', '').strip()
            except requests.exceptions.RequestException as e:
                self.log_message(f"调用Gemini AI API失败或超时：{e}")
                return "Gemini AI调用失败。"

        return "无法获取AI答案，请检查配置。"

    def check_and_sign_in(self, driver):
        try:
            sign_in_button_xpath = '//span[contains(text(), "签到")]'
            sign_in_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, sign_in_button_xpath))
            )
            self.log_message("检测到签到。")
            self.send_wechat_notification("自动签到提醒", "课程有签到任务，正在自动签到。")
            sign_in_button.click()
            self.log_message("已成功自动签到。")
        except (TimeoutException, NoSuchElementException, ElementNotInteractableException):
            pass

    def answer(self, driver):
        try:
            quiz_notification_xpath = '//*[contains(text(), "你有新的课堂习题")]'
            new_quiz_element = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, quiz_notification_xpath))
            )
            self.log_message("发现新的课堂习题，已点击提示。")
            new_quiz_element.click()
        except (TimeoutException, ElementNotInteractableException):
            self.log_message("未找到习题提示，正在检查是否有未提交习题...")
            try:
                submit_button_xpath = '//div[contains(@class, "submit-btn") and contains(text(), "提交答案")]'
                WebDriverWait(driver, 1).until(
                    EC.element_to_be_clickable((By.XPATH, submit_button_xpath))
                )
                self.log_message("检测到未提交的习题，正在准备答题。")
            except (TimeoutException, ElementNotInteractableException):
                self.log_message("未检测到新的习题或未提交的习题。")
                return

        try:
            # 尝试找到主观题的“作答”按钮
            answer_button_xpath = '//div[contains(@class, "submit-btn") and contains(text(), "作答")]'
            WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, answer_button_xpath)))

            # 如果找到，说明是主观题
            self.log_message("检测到主观题（'作答'按钮），正在尝试获取AI答案。")

            question_image = WebDriverWait(driver, 3).until(
                wait_for_image_src(
                    (By.XPATH, '//section[contains(@class, "slide__cmp")]//img[contains(@class, "cover")]'))
            )
            image_url = question_image.get_attribute('src')
            ai_answer = self.get_ai_answer(image_url, question_type="subjective")

            self.log_message(f"AI给出的答案是：{ai_answer}")
            self.send_wechat_notification("自动答题提醒",
                                          f"课程检测到主观题，已跳过作答。以下是AI给出的参考答案：\n\n{ai_answer}")
            return

        except (TimeoutException, NoSuchElementException):
            self.log_message("未检测到主观题，继续尝试客观题答题。")

        try:
            self.log_message("正在等待习题容器加载...")
            question_container = WebDriverWait(driver, 1).until(
                EC.visibility_of_element_located((By.XPATH, '//section[contains(@class, "slide__cmp")]'))
            )
            self.log_message("习题容器已加载，正在等待题目图片...")
            question_image = WebDriverWait(question_container, 1).until(
                wait_for_image_src((By.XPATH, './/img[contains(@class, "cover")]'))
            )
            image_url = question_image.get_attribute('src')
            self.log_message(f"题目图片链接已成功捕获，URL为：{image_url}")

            predicted_options_str = self.get_ai_answer(image_url, question_type="objective")

            is_option_clicked = False

            # --- START: 验证并处理 AI 答案的逻辑 ---
            if predicted_options_str and "调用失败" not in predicted_options_str:
                # 过滤出有效的字母和逗号
                cleaned_answer = ''.join(c for c in predicted_options_str.upper() if 'A' <= c <= 'Z' or c == ',')

                # 再次验证，确保清洗后的答案不为空且只包含有效的答案字符
                valid_options = [opt.strip() for opt in cleaned_answer.split(',') if
                                 opt.strip() in ['A', 'B', 'C', 'D']]  # 假设只有 A,B,C,D

                if valid_options:
                    self.log_message(f"AI预测的答案是：{', '.join(valid_options)}")
                    for option in valid_options:
                        answer_xpath = f'//p[@data-option="{option}"]'
                        try:
                            answer_element = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, answer_xpath))
                            )
                            answer_element.click()
                            is_option_clicked = True
                        except (TimeoutException, NoSuchElementException, ElementNotInteractableException):
                            self.log_message(f"未能点击选项 {option}。")
                else:
                    self.log_message(f"AI返回了无效的答案：{predicted_options_str}。将尝试默认选项。")
            else:
                self.log_message("AI未能提供有效答案或返回了错误信息，将尝试默认选项。")
            # --- END: 验证并处理 AI 答案的逻辑 ---

            if not is_option_clicked:
                self.log_message("AI未能提供有效答案或未能成功点击预测选项，将选择默认选项 A。")
                answer_xpath = '//p[@data-option="A"]'
                try:
                    answer_element = WebDriverWait(driver, 1).until(
                        EC.element_to_be_clickable((By.XPATH, answer_xpath)))
                    answer_element.click()
                    self.log_message("已成功选择默认选项 A。")
                except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
                    self.log_message(f"无法点击默认选项A，错误信息: {e}")

            submit_button_xpath = '//div[contains(@class, "submit-btn") and contains(text(), "提交答案")]'
            submit_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, submit_button_xpath)))
            self.log_message("尝试使用JavaScript提交答案。")
            driver.execute_script("arguments[0].click();", submit_button)
            self.log_message("已提交答案。")
        except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
            self.log_message(f"无法完成答题流程，可能找不到题目或选项。错误信息: {e}")
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = AutoClassBotApp(root)
    root.mainloop()