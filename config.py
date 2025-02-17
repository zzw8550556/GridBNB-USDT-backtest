import os
from dotenv import load_dotenv
import logging

load_dotenv()

SYMBOL = 'BNB/USDT'
INITIAL_GRID = 2.0
FLIP_THRESHOLD = lambda grid_size: (grid_size / 5) / 100  # 网格大小的1/5的1%
POSITION_SCALE_FACTOR = 0.2  # 仓位调整系数（20%）
USE_MARGIN = False  # 禁用保证金账户
MIN_TRADE_AMOUNT = 20.0  # 新下限
MIN_POSITION_PERCENT = 0.05  # 最小交易比例（总资产的5%）
MAX_POSITION_PERCENT = 0.15  # 最大交易比例（总资产的15%）
COOLDOWN = 60
SAFETY_MARGIN = 0.95
MAX_DRAWDOWN = -0.15
DAILY_LOSS_LIMIT = -0.05
MAX_POSITION_RATIO = 0.9  # 最大仓位比例 (90%)，保留10%底仓
MIN_POSITION_RATIO = 0.1  # 最小仓位比例 (10%)，底仓
FEAR_GREED_URL = "https://api.alternative.me/fng/"
PUSHPLUS_TOKEN = os.getenv('PUSHPLUS_TOKEN')
LOG_LEVEL = logging.INFO  # 设置为INFO减少调试日志
DEBUG_MODE = False  # 设置为True时显示详细日志
API_TIMEOUT = 10000  # API超时时间（毫秒）
RECV_WINDOW = 5000  # 接收窗口时间（毫秒）
RISK_CHECK_INTERVAL = 300  # 5分钟检查一次风控
try:
    INITIAL_BASE_PRICE = float(os.getenv('INITIAL_BASE_PRICE', 0))
except ValueError:
    INITIAL_BASE_PRICE = 0
    logging.warning("无效的INITIAL_BASE_PRICE配置，已重置为0")
MAX_RETRIES = 5  # 最大重试次数
RISK_FACTOR = 0.1    # 风险系数（10%）
VOLATILITY_WINDOW = 24  # 波动率计算周期（小时）

class TradingConfig:
    RISK_PARAMS = {
        'max_drawdown': MAX_DRAWDOWN,
        'daily_loss_limit': DAILY_LOSS_LIMIT,
        'position_limit': MAX_POSITION_RATIO
    }
    GRID_PARAMS = {
        'initial': INITIAL_GRID,
        'min': 1.0,
        'max': 4.0,
        'adjust_interval': 1.0,  # 每1小时检查一次
        'volatility_threshold': {
            'ranges': [
                {'range': [0, 0.15], 'grid': 1.0},     # 波动率 0-15%，网格1%
                {'range': [0.15, 0.25], 'grid': 1.5},  # 波动率 15-25%，网格1.5%
                {'range': [0.25, 0.35], 'grid': 2.0},  # 波动率 25-35%，网格2%
                {'range': [0.35, 0.45], 'grid': 3.0},  # 波动率 35-45%，网格3%
                {'range': [0.45, 999], 'grid': 4.0}    # 波动率 >45%，网格4%
            ]
        }
    }
    SYMBOL = SYMBOL
    INITIAL_BASE_PRICE = INITIAL_BASE_PRICE
    RISK_CHECK_INTERVAL = RISK_CHECK_INTERVAL
    MAX_RETRIES = MAX_RETRIES
    RISK_FACTOR = RISK_FACTOR
    BASE_AMOUNT = 50.0  # 恢复原始基础金额（可调整）
    MIN_TRADE_AMOUNT = MIN_TRADE_AMOUNT
    MAX_POSITION_RATIO = MAX_POSITION_RATIO
    MIN_POSITION_RATIO = MIN_POSITION_RATIO
    VOLATILITY_WINDOW = VOLATILITY_WINDOW
    INITIAL_GRID = INITIAL_GRID
    POSITION_SCALE_FACTOR = POSITION_SCALE_FACTOR
    COOLDOWN = COOLDOWN
    SAFETY_MARGIN = SAFETY_MARGIN
    API_TIMEOUT = API_TIMEOUT
    RECV_WINDOW = RECV_WINDOW
    MIN_POSITION_PERCENT = MIN_POSITION_PERCENT
    MAX_POSITION_PERCENT = MAX_POSITION_PERCENT

    def __init__(self):
        # 添加配置验证
        if self.MIN_POSITION_RATIO >= self.MAX_POSITION_RATIO:
            raise ValueError("底仓比例不能大于或等于最大仓位比例")
        
        if self.GRID_PARAMS['min'] > self.GRID_PARAMS['max']:
            raise ValueError("网格最小值不能大于最大值")
        
        self.RISK_PARAMS = {
            'max_drawdown': MAX_DRAWDOWN,
            'daily_loss_limit': DAILY_LOSS_LIMIT,
            'position_limit': MAX_POSITION_RATIO
        }
        self.GRID_PARAMS = {
            'initial': INITIAL_GRID,
            'min': 1.0,
            'max': 4.0,
            'adjust_interval': 1.0,  # 每1小时检查一次
            'volatility_threshold': {
                'ranges': [
                    {'range': [0, 0.15], 'grid': 1.0},     # 波动率 0-15%，网格1%
                    {'range': [0.15, 0.25], 'grid': 1.5},  # 波动率 15-25%，网格1.5%
                    {'range': [0.25, 0.35], 'grid': 2.0},  # 波动率 25-35%，网格2%
                    {'range': [0.35, 0.45], 'grid': 3.0},  # 波动率 35-45%，网格3%
                    {'range': [0.45, 999], 'grid': 4.0}    # 波动率 >45%，网格4%
                ]
            }
        }
        self.SYMBOL = SYMBOL
        self.INITIAL_BASE_PRICE = INITIAL_BASE_PRICE
        self.RISK_CHECK_INTERVAL = RISK_CHECK_INTERVAL
        self.MAX_RETRIES = MAX_RETRIES
        self.RISK_FACTOR = RISK_FACTOR
        self.BASE_AMOUNT = 50.0  # 恢复原始基础金额（可调整）
        self.MIN_TRADE_AMOUNT = MIN_TRADE_AMOUNT
        self.MAX_POSITION_RATIO = MAX_POSITION_RATIO
        self.MIN_POSITION_RATIO = MIN_POSITION_RATIO
        self.MIN_POSITION_PERCENT = MIN_POSITION_PERCENT
        self.MAX_POSITION_PERCENT = MAX_POSITION_PERCENT

    def update_risk_params(self):
        self.RISK_PARAMS = {
            'max_drawdown': MAX_DRAWDOWN,
            'daily_loss_limit': DAILY_LOSS_LIMIT,
            'position_limit': MAX_POSITION_RATIO
        }

    def update_grid_params(self):
        self.GRID_PARAMS = {
            'initial': INITIAL_GRID,
            'min': 1.0,
            'max': 4.0,
            'adjust_interval': 1.0,  # 每1小时检查一次
            'volatility_threshold': {
                'ranges': [
                    {'range': [0, 0.15], 'grid': 1.0},     # 波动率 0-15%，网格1%
                    {'range': [0.15, 0.25], 'grid': 1.5},  # 波动率 15-25%，网格1.5%
                    {'range': [0.25, 0.35], 'grid': 2.0},  # 波动率 25-35%，网格2%
                    {'range': [0.35, 0.45], 'grid': 3.0},  # 波动率 35-45%，网格3%
                    {'range': [0.45, 999], 'grid': 4.0}    # 波动率 >45%，网格4%
                ]
            }
        }

    def update_symbol(self, new_symbol):
        self.SYMBOL = new_symbol

    def update_initial_base_price(self, new_price):
        self.INITIAL_BASE_PRICE = new_price

    def update_risk_check_interval(self, new_interval):
        self.RISK_CHECK_INTERVAL = new_interval

    def update_max_retries(self, new_retries):
        self.MAX_RETRIES = new_retries

    def update_risk_factor(self, new_factor):
        self.RISK_FACTOR = new_factor

    def update_base_amount(self, new_amount):
        self.BASE_AMOUNT = new_amount

    def update_min_trade_amount(self, new_amount):
        self.MIN_TRADE_AMOUNT = new_amount

    def update_max_position_ratio(self, new_ratio):
        self.MAX_POSITION_RATIO = new_ratio

    def update_min_position_ratio(self, new_ratio):
        self.MIN_POSITION_RATIO = new_ratio

    def update_all(self, new_symbol, new_price, new_interval, new_retries, 
                  new_factor, new_amount, new_min_amount, new_ratio):
        self.update_symbol(new_symbol)
        self.update_initial_base_price(new_price)
        self.update_risk_check_interval(new_interval)
        self.update_max_retries(new_retries)
        self.update_risk_factor(new_factor)
        self.update_base_amount(new_amount)
        self.update_min_trade_amount(new_min_amount)
        self.update_max_position_ratio(new_ratio)
        self.update_min_position_ratio(MIN_POSITION_RATIO)
        self.update_risk_params()
        self.update_grid_params()

    def validate_config(self):
        """验证配置参数的有效性"""
        if self.BASE_AMOUNT <= 0:
            raise ValueError("基础交易金额必须大于0")
        
        if not (0 < self.MIN_POSITION_RATIO < self.MAX_POSITION_RATIO <= 1):
            raise ValueError("仓位比例设置无效")
        
        if not (0 < self.GRID_PARAMS['min'] < self.GRID_PARAMS['max']):
            raise ValueError("网格范围设置无效")
        
        return True 