import os
from dotenv import load_dotenv
import logging

load_dotenv()

SYMBOL = 'BNB/USDT'
INITIAL_GRID = 2.0
FLIP_THRESHOLD = lambda grid_size: (grid_size / 5) / 100  # 网格大小的1/5的1%
POSITION_SCALE_FACTOR = 0.2  # 仓位调整系数（20%）
MIN_TRADE_AMOUNT = 20.0  # 新下限
MIN_POSITION_PERCENT = 0.05  # 最小交易比例（总资产的5%）
MAX_POSITION_PERCENT = 0.15  # 最大交易比例（总资产的15%）
COOLDOWN = 60
SAFETY_MARGIN = 0.95
MAX_DRAWDOWN = -0.15
DAILY_LOSS_LIMIT = -0.05
MAX_POSITION_RATIO = 0.9  # 最大仓位比例 (90%)，保留10%底仓
MIN_POSITION_RATIO = 0.1  # 最小仓位比例 (10%)，底仓
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

# 从环境变量读取初始本金，如果未设置或无效，默认为0
try:
    INITIAL_PRINCIPAL = float(os.getenv('INITIAL_PRINCIPAL', 0))
    if INITIAL_PRINCIPAL <= 0:
        logging.warning("INITIAL_PRINCIPAL 必须为正数，已重置为0")
        INITIAL_PRINCIPAL = 0
except ValueError:
    INITIAL_PRINCIPAL = 0
    logging.warning("无效的INITIAL_PRINCIPAL配置，已重置为0")

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
                {'range': [0, 0.20], 'grid': 1.0},     # 波动率 0-20%，网格1.0%
                {'range': [0.20, 0.40], 'grid': 1.5},  # 波动率 20-40%，网格1.5%
                {'range': [0.40, 0.60], 'grid': 2.0},  # 波动率 40-60%，网格2.0%
                {'range': [0.60, 0.80], 'grid': 2.5},  # 波动率 60-80%，网格2.5%
                {'range': [0.80, 1.00], 'grid': 3.0},  # 波动率 80-100%，网格3.0%
                {'range': [1.00, 1.20], 'grid': 3.5},  # 波动率 100-120%，网格3.5%
                {'range': [1.20, 999], 'grid': 4.0}    # 波动率 >120%，网格4.0%
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
    # 添加初始本金到类属性
    INITIAL_PRINCIPAL = INITIAL_PRINCIPAL

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
                    {'range': [0, 0.20], 'grid': 1.0},     # 波动率 0-20%，网格1.0%
                    {'range': [0.20, 0.40], 'grid': 1.5},  # 波动率 20-40%，网格1.5%
                    {'range': [0.40, 0.60], 'grid': 2.0},  # 波动率 40-60%，网格2.0%
                    {'range': [0.60, 0.80], 'grid': 2.5},  # 波动率 60-80%，网格2.5%
                    {'range': [0.80, 1.00], 'grid': 3.0},  # 波动率 80-100%，网格3.0%
                    {'range': [1.00, 1.20], 'grid': 3.5},  # 波动率 100-120%，网格3.5%
                    {'range': [1.20, 999], 'grid': 4.0}    # 波动率 >120%，网格4.0%
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
        # 将初始本金赋值给实例属性
        self.INITIAL_PRINCIPAL = INITIAL_PRINCIPAL

    # Removed unused update methods (update_risk_params, update_grid_params, 
    # update_symbol, update_initial_base_price, update_risk_check_interval, 
    # update_max_retries, update_risk_factor, update_base_amount, 
    # update_min_trade_amount, update_max_position_ratio, 
    # update_min_position_ratio, update_all)

    # Removed unused validate_config method
# End of class definition 