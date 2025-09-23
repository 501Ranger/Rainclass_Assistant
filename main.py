import os
import json
import time
import requests
import base64
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# 设置全局 driver 变量
global driver
# 设置你的 Gemini API Key
GEMINI_API_KEY = "AIzaSyCK-8xCpBa7iKuJZnOwrH7scil2JMMrc0Y"

# xxtui 的 API Key，请访问 https://www.xxtui.com/ 获取并替换为您自己的 Key
XXTUI_API_KEY = "1dfd55d4bf3ce6b4"


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


def getCookies():
    """
    通过手动登录获取并保存 cookies 到 'cookies.txt' 文件。
    """
    # 初始化 ChromeOptions
    chrome_options = Options()
    # 禁用沙盒模式，在某些服务器环境下是必需的
    chrome_options.add_argument('--no-sandbox')
    # 禁用 /dev/shm 使用，避免某些内存问题
    chrome_options.add_argument('--disable-dev-shm-usage')

    # 使用 Service 对象并传入 ChromeDriverManager().install() 来自动管理驱动
    service = Service(ChromeDriverManager().install())
    # 将 options 参数传递给 driver
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.get('https://changjiang.yuketang.cn')
    print("bot: 请在弹出的浏览器窗口中完成登录。你有120秒的时间。")
    # 等待学生标签出现，表示登录成功
    WebDriverWait(driver, 120).until(EC.presence_of_element_located((By.ID, 'tab-student')))
    cookies = driver.get_cookies()
    f1 = open("cookies.txt", "w")
    f1.write(json.dumps(cookies))
    f1.close()
    print("bot: Cookies 已成功保存。")
    driver.quit()  # 使用 quit() 退出浏览器


def getIntoClass():
    """
    使用保存的 cookies 登录并尝试进入正在进行的课程。
    """
    now_time = time.strftime("%H:%M", time.localtime())
    # 初始化 ChromeOptions
    chrome_options = Options()
    # 禁用沙盒模式
    chrome_options.add_argument('--no-sandbox')
    # 禁用 /dev/shm 使用
    chrome_options.add_argument('--disable-dev-shm-usage')

    # 使用 Service 对象并传入 ChromeDriverManager().install() 来自动管理驱动
    service = Service(ChromeDriverManager().install())
    # 将 options 参数传递给 driver
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.get('https://changjiang.yuketang.cn')

    if not os.path.exists("cookies.txt"):
        print("bot: 未找到 cookies.txt，请先运行 getCookies() 函数获取。")
        driver.quit()
        return False

    f2 = open("cookies.txt")
    cookies = json.loads(f2.read())
    for cook in cookies:
        # 添加 cookies 需要注意 domain
        driver.add_cookie(cook)
    driver.refresh()

    try:
        # 首先等待页面加载完成
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))

        # 显式等待 "jump_lesson__bar" 元素消失，解决 ElementClickInterceptedException
        print(f"{now_time} bot: 等待加载条消失...")
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.XPATH, '//*[contains(@class, "jump_lesson__bar")]'))
        )

        # 尝试点击学生标签
        print(f"{now_time} bot: 尝试点击学生标签...")
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'tab-student'))
        ).click()
        print(f"{now_time} bot: 成功点击学生标签。")

    except (TimeoutException, ElementNotInteractableException) as e:
        print(f"{now_time} bot: 未能点击学生标签，尝试直接寻找正在进行的课程...")
        pass  # 继续执行下一步，尝试直接寻找正在进行的课程

    try:
        print(f"{now_time} bot: 正在检查是否有正在进行的课程...")
        class_element_xpath = '//*[contains(@class, "onlesson")]'
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, class_element_xpath)))
        driver.find_element(By.XPATH, class_element_xpath).click()

        print("bot: 我去上课啦")
        print("bot: 我将会每10s检测一次随堂测试和签到，直到下课。")
        # 切换到课程页面
        driver.switch_to.window(driver.window_handles[len(driver.window_handles) - 1])

        while True:
            # 检查是否下课
            try:
                # 尝试查找下课元素
                if driver.find_elements(By.XPATH, '//div[@title="下课啦！" and contains(@class, "timeline__msg")]'):
                    print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 检测到下课啦！自动答题已停止。")
                    break
            except NoSuchElementException:
                # 如果找不到元素，说明还在上课，继续
                pass

            # 如果没有下课，继续自动答题和签到
            time.sleep(10)
            check_and_sign_in(driver)
            answer(driver)

    except TimeoutException:
        print(f"{now_time} bot: 你现在没课")
        driver.quit()
        return False
    except Exception as e:
        print(f"{now_time} bot: 发生意外错误：{e}")
        driver.quit()
        return False

    return True


def send_wechat_notification(title, content):
    """
    使用 xxtui 发送微信通知。

    Args:
        title (str): 消息的标题。
        content (str): 消息的详细内容。
    """
    if XXTUI_API_KEY == "YOUR_XXTUI_API_KEY_HERE":
        print("bot: 警告！请设置您的 XXTUI_API_KEY 以启用微信通知功能。")
        return

    api_url = f"https://www.xxtui.com/xxtui/{XXTUI_API_KEY}"

    headers = {
        'Content-Type': 'application/json'
    }

    data = {
        "from": "课堂机器人",  # 明确指定来源，便于区分
        "title": title,
        "content": content,
        "channel": "WX_MP"  # 明确指定渠道为微信公众号
    }

    print(f"bot: 正在向 xxtui 发送通知。URL: {api_url}, Payload: {data}")

    try:
        response = requests.post(api_url, headers=headers, json=data, timeout=5)
        response.raise_for_status()
        result = response.json()
        if result.get('code') == 0:
            print("bot: 微信通知发送成功。")
        else:
            print(f"bot: 微信通知发送失败，错误码：{result.get('code')}，错误信息：{result.get('message')}")
    except requests.exceptions.RequestException as e:
        print(f"bot: 发送微信通知时发生错误：{e}")


def get_ai_answer(image_url):
    """
    调用 Gemini API 获取习题答案。

    Args:
        image_url (str): 题目图片 URL。

    Returns:
        str: AI 预测的最佳选项（如 'A,B'），如果失败则返回 None。
    """
    if GEMINI_API_KEY == "your_api_key_here":
        print("bot: 警告！请在代码中设置您的 GEMINI_API_KEY 以启用 AI 答题功能。")
        return None

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={GEMINI_API_KEY}"

    # 下载图片
    try:
        image_response = requests.get(image_url, timeout=10)
        image_response.raise_for_status()
        image_bytes = image_response.content
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    except requests.exceptions.RequestException as e:
        print(f"bot: 下载图片失败：{e}")
        return None

    prompt = "看这张图片，请找出图中的习题。如果是单选题，请只返回一个选项字母（如 A）。如果是多选题，请返回所有正确选项的字母，并用逗号分隔（如 A,B,C）。如果无法确定，请返回 'C'。"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64_image
                        }
                    }
                ]
            }
        ]
    }

    try:
        # 将超时时间设置为8秒
        response = requests.post(api_url, json=payload, timeout=8)
        response.raise_for_status()

        result = response.json()
        candidate = result.get('candidates', [{}])[0]
        answer_text = candidate.get('content', {}).get('parts', [{}])[0].get('text', '').strip().upper()

        # 移除答案文本中的非字母和非逗号字符
        cleaned_answer = ''.join(c for c in answer_text if 'A' <= c <= 'Z' or c == ',')

        if cleaned_answer:
            print(f"bot: AI 预测的答案是：{cleaned_answer}")
            return cleaned_answer

        print("bot: AI 未返回有效的答案选项。")
        return None

    except requests.exceptions.RequestException as e:
        print(f"bot: 调用 Gemini API 失败或超时：{e}")
        return None


def check_and_sign_in(driver):
    """
    检测签到并自动签到。
    """
    try:
        # 尝试寻找签到按钮
        sign_in_button_xpath = '//span[contains(text(), "签到")]'
        sign_in_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, sign_in_button_xpath))
        )

        # 获取群聊名称用于通知，使用更健壮的等待
        try:
            class_name_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a.text-ellipsis[title]'))
            )
            class_name = class_name_element.get_attribute('title')
        except TimeoutException:
            print("bot: 无法获取课程名称，通知中将使用默认值。")
            class_name = "未知课程"

        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 检测到签到。")
        send_wechat_notification("自动签到提醒", f"课程【{class_name}】有签到任务，正在自动签到。")

        sign_in_button.click()
        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 已成功自动签到。")
    except (TimeoutException, NoSuchElementException, ElementNotInteractableException):
        # 没有找到签到按钮，忽略
        pass


def answer(driver):
    """
    检测课堂习题并自动选择 AI 预测的选项提交。
    """
    try:
        # 尝试寻找新的课堂习题提示
        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 正在尝试检测习题提示...")
        quiz_notification_xpath = '//*[contains(text(), "你有新的课堂习题")]'
        new_quiz_element = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, quiz_notification_xpath))
        )

        # 获取群聊名称用于通知，使用更健壮的等待
        try:
            class_name_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a.text-ellipsis[title]'))
            )
            class_name = class_name_element.get_attribute('title')
        except TimeoutException:
            print("bot: 无法获取课程名称，通知中将使用默认值。")
            class_name = "未知课程"

        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 发现新的课堂习题，已点击提示。")
        send_wechat_notification("自动答题提醒", f"课程【{class_name}】有随堂测试，正在自动作答。")

        new_quiz_element.click()
    except (TimeoutException, ElementNotInteractableException):
        # 如果没有找到新的习题提示，则尝试寻找提交答案按钮
        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 未找到习题提示，正在检查是否有未提交习题...")
        try:
            # 尝试寻找提交按钮作为未提交习题的标志
            submit_button_xpath = '//div[contains(@class, "submit-btn") and contains(text(), "提交答案")]'
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, submit_button_xpath))
            )
            print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 检测到未提交的习题，正在准备答题。")
        except (TimeoutException, ElementNotInteractableException):
            print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 未检测到新的习题或未提交的习题。")
            return

    # 获取群聊名称用于通知
    try:
        class_name_element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a.text-ellipsis[title]'))
        )
        class_name = class_name_element.get_attribute('title')
    except TimeoutException:
        class_name = "未知课程"

    # --- 新增功能：根据按钮文本判断主观题并跳过 ---
    try:
        # 检查提交按钮的文本是“作答”还是“提交答案”
        # 先找“作答”按钮，如果找到，说明是主观题
        answer_button_xpath = '//div[contains(@class, "submit-btn") and contains(text(), "作答")]'
        answer_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, answer_button_xpath))
        )
        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 检测到主观题（'作答'按钮），已跳过作答。")
        send_wechat_notification("自动答题提醒", f"课程【{class_name}】检测到主观题，已跳过作答。请手动处理。")
        return
    except (TimeoutException, NoSuchElementException):
        # 如果没找到“作答”按钮，则继续执行下面的客观题答题逻辑
        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 未检测到主观题，继续尝试客观题答题。")
        pass
    # --- 主观题检测结束 ---

    # 如果上述任一条件满足，则执行答题逻辑
    try:
        # 首先等待整个习题容器加载，确保页面内容已更新
        print(f"bot: 正在等待习题容器加载...")
        question_container = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, '//section[contains(@class, "slide__cmp")]'))
        )
        print(f"bot: 习题容器已加载，正在等待题目图片...")

        # 在习题容器内寻找图片，并使用自定义等待条件确保链接有效
        question_image = WebDriverWait(question_container, 10).until(
            wait_for_image_src((By.XPATH, './/img[contains(@class, "cover")]'))
        )
        image_url = question_image.get_attribute('src')
        print(f"bot: 题目图片链接已成功捕获，URL为：{image_url}")

        # 调用 AI 获取答案
        predicted_options_str = get_ai_answer(image_url)

        if predicted_options_str:
            # 将答案字符串转换为列表，并移除空字符串
            predicted_options = [opt.strip() for opt in predicted_options_str.split(',') if opt.strip()]

            if len(predicted_options) > 0:
                print(f"bot: AI 预测的答案是：{', '.join(predicted_options)}")
                for option in predicted_options:
                    answer_xpath = f'//p[@data-option="{option}"]'
                    try:
                        answer_element = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, answer_xpath))
                        )
                        answer_element.click()
                    except (TimeoutException, NoSuchElementException, ElementNotInteractableException):
                        print(f"bot: 未能点击选项 {option}。")
            else:
                print("bot: AI 未能提供有效的答案，将选择默认选项 A。")
                answer_xpath = f'//p[@data-option="A"]'
                answer_element = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, answer_xpath))
                )
                answer_element.click()
                print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 选择了默认选项 A。")
        else:
            print("bot: AI 未能提供答案或响应超时，将选择默认选项 A。")
            answer_xpath = f'//p[@data-option="A"]'
            answer_element = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, answer_xpath))
            )
            answer_element.click()
            print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 选择了默认选项 A。")

        # 直接尝试点击提交按钮
        submit_button_xpath = '//div[contains(@class, "submit-btn") and contains(text(), "提交答案")]'
        submit_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, submit_button_xpath))
        )
        submit_button.click()
        print(f"{time.strftime('%H:%M:%S', time.localtime())} bot: 已提交答案。")

    except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
        # 如果答题过程中出现问题，打印错误
        print(f"bot: 无法完成答题流程，可能找不到题目或选项。错误信息: {e}")
        pass


if __name__ == "__main__":
    try:
        if os.path.exists("cookies.txt"):
            print("bot: 找到 cookies.txt，将自动登录并检查课程。")
            while True:
                # 检查时间是否在 6:58 到 21:58 之间
                current_hour = time.localtime().tm_hour
                if 0 <= current_hour <= 24:
                    print(f"{time.strftime('%H:%M', time.localtime())} bot: 正在检查是否有正在进行的课程...")
                    getIntoClass()
                else:
                    print(f"{time.strftime('%H:%M', time.localtime())} bot: 当前不在检查时间段内，跳过检查。")
                time.sleep(10)
        else:
            print("bot: Hello，初次相遇需要先做一些设置，手动扫码登录一次，让我获取你的 cookies。")
            getCookies()
            print("bot: 好了, 现在我将在每个整点自动登录一次，如果发现有课就会进入教室上课。")
            print("bot: 挂在后台就好, 去做点真正有用的事情吧。\n")
            getIntoClass()
            while True:
                time.sleep(10)
                getIntoClass()
    except Exception as ex:  # don't you ever stop!
        print(ex)
