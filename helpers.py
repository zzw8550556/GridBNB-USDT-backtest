import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from config import PUSHPLUS_TOKEN
import time
import psutil
import os
from logging.handlers import TimedRotatingFileHandler

def send_pushplus_message(content, title="交易信号通知"):
    if not PUSHPLUS_TOKEN:
        logging.error("未配置PUSHPLUS_TOKEN，无法发送通知")
        return
    
    url = "https://www.pushplus.plus/send"
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "txt"  # 改用文本模板，更可靠
    }
    try:
        logging.info(f"正在发送推送通知: {title}")
        response = requests.post(url, data=data)
        response_json = response.json()
        
        if response.status_code == 200 and response_json.get('code') == 200:
            logging.info(f"消息推送成功: {content}")
        else:
            logging.error(f"消息推送失败: 状态码={response.status_code}, 响应={response_json}")
    except Exception as e:
        logging.error(f"消息推送异常: {str(e)}", exc_info=True)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def safe_fetch(method, *args, **kwargs):
    try:
        return await method(*args, **kwargs)
    except Exception as e:
        logging.error(f"请求失败: {str(e)}")
        raise 

def debug_watcher():
    """资源监控装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start = time.time()
            mem_before = psutil.virtual_memory().used
            logging.debug(f"[DEBUG] 开始执行 {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                cost = time.time() - start
                mem_used = psutil.virtual_memory().used - mem_before
                logging.debug(f"[DEBUG] {func.__name__} 执行完成 | 耗时: {cost:.3f}s | 内存变化: {mem_used/1024/1024:.2f}MB")
        return wrapper
    return decorator 

class LogConfig:
    SINGLE_LOG = True  # 强制单文件模式
    BACKUP_DAYS = 2    # 保留2天日志
    LOG_DIR = os.path.dirname(__file__)  # 与main.py相同目录
    LOG_LEVEL = logging.INFO

    @staticmethod
    def setup_logger():
        logger = logging.getLogger()
        logger.setLevel(LogConfig.LOG_LEVEL)
        
        # 清理所有现有处理器
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 文件处理器
        file_handler = TimedRotatingFileHandler(
            os.path.join(LogConfig.LOG_DIR, 'trading_system.log'),
            when='midnight',
            interval=1,
            backupCount=LogConfig.BACKUP_DAYS,
            encoding='utf-8',
            delay=True
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    @staticmethod
    def clean_old_logs():
        if not os.path.exists(LogConfig.LOG_DIR):
            return
        now = time.time()
        for fname in os.listdir(LogConfig.LOG_DIR):
            if LogConfig.SINGLE_LOG and fname != 'trading_system.log':
                continue
            path = os.path.join(LogConfig.LOG_DIR, fname)
            if os.stat(path).st_mtime < now - LogConfig.BACKUP_DAYS * 86400:
                try:
                    os.remove(path)
                except Exception as e:
                    print(f"删除旧日志失败 {fname}: {str(e)}") 