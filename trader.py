from config import TradingConfig, FLIP_THRESHOLD, SAFETY_MARGIN, COOLDOWN
from exchange_client import ExchangeClient
from order_tracker import OrderTracker, OrderThrottler
from risk_manager import AdvancedRiskManager
import logging
import asyncio
import numpy as np
from datetime import datetime
import time
import math
from helpers import send_pushplus_message
import json
from api import TradingMonitor

class GridTrader:
    def __init__(self, exchange, config):
        """初始化网格交易器"""
        self.exchange = exchange
        self.config = config
        self.symbol = config.SYMBOL
        self.base_price = config.INITIAL_BASE_PRICE
        self.grid_size = config.INITIAL_GRID
        self.initialized = False
        self.highest = None
        self.lowest = None
        self.current_price = None
        self.active_orders = {'buy': None, 'sell': None}
        self.order_tracker = OrderTracker()
        self.risk_manager = AdvancedRiskManager(self)
        self.trend_analyzer = TrendAnalyzer(self)  # 添加趋势分析器
        self.total_assets = 0
        self.last_trade_time = None
        self.last_trade_price = None
        self.price_history = []
        self.last_grid_adjust_time = time.time()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.symbol_info = None
        self.monitored_orders = []
        self.pending_orders = {}
        self.order_timestamps = {}
        self.throttler = OrderThrottler(limit=10, interval=60)
        self.last_price_check = 0  # 新增价格检查时间戳
        self.ORDER_TIMEOUT = 10  # 订单超时时间（秒）
        self.MIN_TRADE_INTERVAL = 30  # 两次交易之间的最小间隔（秒）
        self.grid_params = {
            'base_size': 2.0,     # 基础网格大小
            'min_size': 1.0,      # 最小网格
            'max_size': 4.0,      # 最大网格
            'adjust_step': 0.2    # 调整步长
        }
        self.volatility_window = 24  # 波动率计算周期（小时）
        self.monitor = TradingMonitor(self)  # 初始化monitor
        self.balance_check_interval = 60  # 每60秒检查一次余额
        self.last_balance_check = 0
        self.funding_balance_cache = {
            'timestamp': 0,
            'data': {}
        }
        self.funding_cache_ttl = 60  # 理财余额缓存60秒

    async def initialize(self):
        if self.initialized:
            return
        
        self.logger.info("正在加载市场数据...")
        try:
            # 确保市场数据加载成功
            retry_count = 0
            while not self.exchange.markets_loaded and retry_count < 3:
                try:
                    await self.exchange.load_markets()
                    await asyncio.sleep(1)
                except Exception as e:
                    self.logger.warning(f"加载市场数据失败: {str(e)}")
                    retry_count += 1
                    if retry_count >= 3:
                        raise
                    await asyncio.sleep(2)
            
            # 检查现货账户资金并划转
            await self._check_and_transfer_initial_funds()
            
            self.symbol_info = self.exchange.exchange.market(self.config.SYMBOL)
            
            # 优先使用.env配置的基准价
            if self.config.INITIAL_BASE_PRICE > 0:
                self.base_price = self.config.INITIAL_BASE_PRICE
                self.logger.info(f"使用预设基准价: {self.base_price}")
            else:
                self.base_price = await self._get_latest_price()
                self.logger.info(f"使用实时基准价: {self.base_price}")
            
            if self.base_price is None:
                raise ValueError("无法获取当前价格")
            
            self.logger.info(f"初始化完成 | 交易对: {self.config.SYMBOL} | 基准价: {self.base_price}")
            
            # 发送启动通知
            threshold = FLIP_THRESHOLD(self.grid_size)  # 计算实际阈值
            send_pushplus_message(
                f"网格交易启动成功\n"
                f"交易对: {self.config.SYMBOL}\n"
                f"基准价: {self.base_price} USDT\n"
                f"网格大小: {self.grid_size}%\n"
                f"触发阈值: {threshold*100}% (网格大小的1/5)"
            )
            
            # 添加市场价对比
            market_price = await self._get_latest_price()
            price_diff = (market_price - self.base_price) / self.base_price * 100
            self.logger.info(
                f"市场当前价: {market_price:.4f} | "
                f"价差: {price_diff:+.2f}%"
            )
            self.initialized = True
        except Exception as e:
            self.initialized = False
            self.logger.error(f"初始化失败: {str(e)}")
            # 发送错误通知
            send_pushplus_message(
                f"网格交易启动失败\n"
                f"错误信息: {str(e)}",
                "错误通知"
            )
            raise
    
    async def _get_latest_price(self):
        try:
            ticker = await self.exchange.fetch_ticker(self.config.SYMBOL)
            if ticker and 'last' in ticker:
                return ticker['last']
            self.logger.error("获取价格失败: 返回数据格式不正确")
            return self.base_price
        except Exception as e:
            self.logger.error(f"获取最新价格失败: {str(e)}")
            return self.base_price

    def _get_upper_band(self):
        return self.base_price * (1 + self.grid_size / 100)
    
    def _get_lower_band(self):
        return self.base_price * (1 - self.grid_size / 100)
    
    async def _check_buy_signal(self):
        current_price = self.current_price
        if current_price <= self._get_lower_band():
            # 记录最低价
            new_lowest = current_price if self.lowest is None else min(self.lowest, current_price)
            # 只在最低价更新时打印日志
            if new_lowest != self.lowest:
                self.lowest = new_lowest
                self.logger.info(
                    f"买入监测 | "
                    f"当前价: {current_price:.2f} | "
                    f"触发价: {self._get_lower_band():.5f} | "
                    f"最低价: {self.lowest:.2f} | "
                    f"网格下限: {self._get_lower_band():.2f} | "
                    f"反弹阈值: {FLIP_THRESHOLD(self.grid_size)*100:.2f}%"
                )
            threshold = FLIP_THRESHOLD(self.grid_size)
            # 从最低价反弹指定比例时触发买入
            if self.lowest and current_price >= self.lowest * (1 + threshold):
                self.logger.info(f"触发买入信号 | 当前价: {current_price:.2f} | 已反弹: {(current_price/self.lowest-1)*100:.2f}%")
                return True
        return False
    
    async def _check_sell_signal(self):
        current_price = self.current_price
        if current_price >= self._get_upper_band():
            # 记录最高价
            new_highest = current_price if self.highest is None else max(self.highest, current_price)
            # 只在最高价更新时打印日志
            if new_highest != self.highest:
                self.highest = new_highest
                self.logger.info(
                    f"卖出监测 | "
                    f"当前价: {current_price:.2f} | "
                    f"触发价: {self._get_upper_band():.5f} | "
                    f"最高价: {self.highest:.2f}"
                )
            threshold = FLIP_THRESHOLD(self.grid_size)
            # 从最高价下跌指定比例时触发卖出
            if self.highest and current_price <= self.highest * (1 - threshold):
                self.logger.info(f"触发卖出信号 | 当前价: {current_price:.2f} | 已下跌: {(1-current_price/self.highest)*100:.2f}%")
                return True
        return False
    
    async def _calculate_order_amount(self, order_type):
        """计算订单金额"""
        try:
            current_time = time.time()
            
            # 使用缓存避免频繁计算和日志输出
            cache_key = f'order_amount_{order_type}'
            if hasattr(self, cache_key) and \
               current_time - getattr(self, f'{cache_key}_time') < 60:  # 1分钟缓存
                return getattr(self, cache_key)
            
            current_price = await self._get_latest_price()
            total_assets = await self._get_total_assets()
            
            # 计算订单金额范围
            min_trade_amount = max(
                self.config.MIN_TRADE_AMOUNT,
                total_assets * 0.05
            )
            max_trade_amount = total_assets * 0.15
            
            # 目标金额为总资产的10%
            target_amount = total_assets * 0.1
            
            if order_type == 'buy':
                available_usdt = await self.get_available_balance('USDT')
                amount = min(target_amount, max_trade_amount, available_usdt)
                amount = max(amount, min_trade_amount)
            else:
                # 卖出订单计算
                bnb_balance = float(await self.get_available_balance('BNB'))
                
                # 先计算BNB的等值USDT金额
                bnb_value = bnb_balance * current_price
                
                # 在目标金额和BNB价值之间取较小值
                amount = min(target_amount, bnb_value)
                
                # 确保金额在允许范围内
                amount = min(max(amount, min_trade_amount), max_trade_amount)
                
                # 如果可用BNB价值小于最小交易金额，使用全部可用BNB
                if bnb_value < min_trade_amount:
                    amount = bnb_value
            
            # 根据趋势调整金额
            trend = await self.trend_analyzer.analyze_trend()
            if trend in ['strong_uptrend', 'weak_uptrend']:
                if order_type == 'buy':
                    amount *= 1.2
                else:
                    amount *= 0.8
            elif trend in ['strong_downtrend', 'weak_downtrend']:
                if order_type == 'buy':
                    amount *= 0.6
                else:
                    amount *= 1.2
            
            # 只在金额变化超过1%时记录日志
            if not hasattr(self, f'{cache_key}_last') or \
               abs(amount - getattr(self, f'{cache_key}_last')) / getattr(self, f'{cache_key}_last') > 0.01:
                self.logger.info(
                    f"订单金额计算 | "
                    f"类型: {order_type} | "
                    f"目标金额: {target_amount:.2f} | "
                    f"最小金额: {min_trade_amount:.2f} | "
                    f"最大金额: {max_trade_amount:.2f} | "
                    f"{'USDT' if order_type == 'buy' else 'BNB'}余额: "
                    f"{await self.get_available_balance('USDT' if order_type == 'buy' else 'BNB'):.4f} | "
                    f"当前价格: {current_price:.2f} | "
                    f"调整后金额: {amount:.2f} | "
                    f"趋势: {trend}"
                )
                setattr(self, f'{cache_key}_last', amount)
            
            # 更新缓存
            setattr(self, cache_key, amount)
            setattr(self, f'{cache_key}_time', current_time)
            
            return amount
            
        except Exception as e:
            self.logger.error(f"计算订单金额失败: {str(e)}")
            return 0
    
    async def get_available_balance(self, currency):
        balance = await self.exchange.fetch_balance({'type': 'spot'})
        return balance.get('free', {}).get(currency, 0) * SAFETY_MARGIN
    
    async def main_loop(self):
        """主交易循环"""
        while True:
            try:
                if not self.initialized:
                    await self.initialize()
                
                # 获取当前价格
                current_price = await self._get_latest_price()
                if not current_price:
                    continue
                
                self.current_price = current_price
                
                # 判断是否在监控状态
                in_monitoring = (
                    (current_price >= self._get_upper_band() and self.highest is not None) or  # 卖出监控
                    (current_price <= self._get_lower_band() and self.lowest is not None)      # 买入监控
                )
                
                # 根据状态设置不同的延迟
                delay = 2 if in_monitoring else 5
                
                await asyncio.sleep(delay)  # 根据状态调整检测间隔
                
                # 检查是否需要调整网格大小
                if self.last_grid_adjust_time and \
                   time.time() - self.last_grid_adjust_time > self.config.GRID_PARAMS['adjust_interval'] * 3600:
                    await self.adjust_grid_size()
                    self.last_grid_adjust_time = time.time()
                
                # 检查风控
                if await self.risk_manager.multi_layer_check():
                    continue
                
                # 检查买卖信号
                if await self._check_sell_signal():
                    await self.execute_order('sell')
                elif await self._check_buy_signal():
                    await self.execute_order('buy')
                    
            except Exception as e:
                self.logger.error(f"交易循环异常: {str(e)}")

    async def _ensure_trading_funds(self):
        """确保现货账户有足够的交易资金"""
        try:
            balance = await self.exchange.fetch_balance()
            current_price = self.current_price
            
            # 计算所需资金
            required_usdt = self.config.MIN_TRADE_AMOUNT * 2  # 保持两倍最小交易额
            required_bnb = required_usdt / current_price
            
            # 获取现货余额
            spot_usdt = float(balance['free'].get('USDT', 0))
            spot_bnb = float(balance['free'].get('BNB', 0))
            
            # 一次性检查和赎回所需资金
            transfers = []
            if spot_usdt < required_usdt:
                transfers.append({
                    'asset': 'USDT',
                    'amount': required_usdt - spot_usdt
                })
            if spot_bnb < required_bnb:
                transfers.append({
                    'asset': 'BNB',
                    'amount': required_bnb - spot_bnb
                })
            
            # 如果需要赎回，一次性执行所有赎回操作
            if transfers:
                self.logger.info("开始资金赎回操作...")
                for transfer in transfers:
                    self.logger.info(f"从理财赎回 {transfer['amount']:.8f} {transfer['asset']}")
                    await self.exchange.transfer_to_spot(transfer['asset'], transfer['amount'])
                self.logger.info("资金赎回完成")
                # 等待资金到账
                await asyncio.sleep(2)
        except Exception as e:
            self.logger.error(f"资金检查和划转失败: {str(e)}")

    async def emergency_stop(self):
        try:
            open_orders = await self.exchange.fetch_open_orders(self.config.SYMBOL)
            for order in open_orders:
                await self.exchange.cancel_order(order['id'])
            send_pushplus_message("程序紧急停止", "系统通知")
            self.logger.critical("所有交易已停止，进入复盘程序")
        except Exception as e:
            self.logger.error(f"紧急停止失败: {str(e)}")
            send_pushplus_message(f"程序异常停止: {str(e)}", "错误通知")
        finally:
            await self.exchange.close()
            exit()

    async def _get_position_ratio(self):
        """获取当前仓位占总资产比例"""
        try:
            usdt_balance = await self.get_available_balance('USDT')
            position_value = await self.risk_manager._get_position_value()
            total_assets = position_value + usdt_balance
            if total_assets == 0:
                return 0
            return position_value / total_assets
        except Exception as e:
            self.logger.error(f"获取仓位比例失败: {str(e)}")
            return 0

    async def _get_daily_pnl(self):
        """获取当日盈亏比例（示例实现）"""
        # TODO: 实现实际盈亏计算逻辑
        return 0

    async def execute_order(self, side):
        """执行订单"""
        try:
            # 获取订单簿数据
            order_book = await self.exchange.fetch_order_book(self.config.SYMBOL, limit=5)
            if not order_book:
                self.logger.error("获取订单簿失败")
                return False
            
            # 使用买1/卖1价格
            if side == 'buy':
                order_price = order_book['asks'][0][0]  # 卖1价买入
            else:
                order_price = order_book['bids'][0][0]  # 买1价卖出
            
            # 计算交易数量
            amount_usdt = await self._calculate_order_amount(side)
            amount = self._adjust_amount_precision(amount_usdt / order_price)
            
            self.logger.info(
                f"创建{side}单 | "
                f"价格: {order_price} | "
                f"动态金额: {amount_usdt:.2f} USDT | "
                f"数量: {amount:.4f} BNB"
            )
            
            # 创建订单
            order = await self.exchange.create_order(
                self.config.SYMBOL,
                'limit',
                side,
                amount,
                order_price
            )
            
            # 更新活跃订单状态
            self.active_orders[side] = order['id']
            self.order_tracker.add_order(order)
            
            # 缩短等待时间到3秒
            await asyncio.sleep(3)
            updated_order = await self.exchange.fetch_order(order['id'], self.config.SYMBOL)
            
            # 如果订单已成交，更新状态并返回
            if updated_order['status'] == 'closed':
                self.logger.info("订单已成交")
                # 更新基准价
                self.base_price = float(updated_order['price'])
                # 清除活跃订单状态
                self.active_orders[side] = None
                
                # 更新交易记录，确保web页面能显示
                trade_info = {
                    'timestamp': time.time(),
                    'side': side,
                    'price': float(updated_order['price']),
                    'amount': float(updated_order['amount']),
                    'profit': 0,  # 这里可以计算实际利润
                    'order_id': updated_order['id']
                }
                self.order_tracker.add_trade(trade_info)
                
                # 更新最后交易时间和价格
                self.last_trade_time = time.time()
                self.last_trade_price = float(updated_order['price'])
                
                # 更新总资产信息
                await self._update_total_assets()
                
                self.logger.info(f"基准价已更新: {self.base_price}")
                
                # 发送通知
                send_pushplus_message(
                    f"网格交易信号通知\n"
                    f"操作：{'买入' if side == 'buy' else '卖出'} {self.config.SYMBOL}\n"
                    f"交易对：{self.config.SYMBOL}\n"
                    f"价格：{order_price}\n"
                    f"数量：{amount}\n"
                    f"金额：{amount_usdt:.2f} USDT\n"
                    f"网格范围：{self.grid_size}%\n"
                    f"触发阈值：{FLIP_THRESHOLD(self.grid_size)*100:.2f}%"
                )
                
                return order
            
            # 如果订单未成交，取消订单
            self.logger.warning("订单未成交，尝试取消")
            try:
                await self.exchange.cancel_order(order['id'], self.config.SYMBOL)
            except Exception as e:
                self.logger.error(f"取消订单失败: {str(e)}")
            
            # 清除活跃订单状态
            self.active_orders[side] = None
            
            # 发送错误通知
            send_pushplus_message(
                f"网格交易错误通知\n"
                f"操作：{'买入' if side == 'buy' else '卖出'}失败\n"
                f"交易对：{self.config.SYMBOL}\n"
                f"错误信息：订单未能成交",
                "错误通知"
            )
            
            return False
            
        except Exception as e:
            self.logger.error(f"执行{side}单失败: {str(e)}")
            # 发送错误通知
            send_pushplus_message(
                f"网格交易错误通知\n"
                f"操作：{'买入' if side == 'buy' else '卖出'}失败\n"
                f"交易对：{self.config.SYMBOL}\n"
                f"错误信息：{str(e)}",
                "错误通知"
            )
            return False

    async def _wait_for_balance(self, side, amount, price):
        """等待直到有足够的余额可用"""
        max_attempts = 10
        for i in range(max_attempts):
            balance = await self.exchange.fetch_balance()
            if side == 'buy':
                required = amount * price
                available = float(balance['free'].get('USDT', 0))
                if available >= required:
                    return True
            else:
                available = float(balance['free'].get('BNB', 0))
                if available >= amount:
                    return True
            
            self.logger.info(f"等待资金到账 ({i+1}/{max_attempts})...")
            await asyncio.sleep(1)
        
        raise Exception("等待资金到账超时")

    def _calculate_trade_profit(self, order):
        """计算交易利润"""
        try:
            if not self.last_trade_price:
                return 0
            
            current_price = float(order['price'])
            if order['side'] == 'sell':
                return (current_price - self.last_trade_price) / self.last_trade_price
            else:
                return (self.last_trade_price - current_price) / current_price
        except Exception as e:
            self.logger.error(f"计算利润失败: {str(e)}")
            return 0

    async def _adjust_grid_after_trade(self):
        """根据市场波动动态调整网格大小"""
        trade_count = self.order_tracker.trade_count
        if trade_count % self.config.GRID_PARAMS['adjust_interval'] == 0:
            volatility = await self._calculate_volatility()
            
            # 根据波动率调整
            if volatility > self.config.GRID_PARAMS['volatility_threshold']['high']:
                new_size = min(
                    self.grid_size * 1.1,  # 扩大10%
                    self.config.GRID_PARAMS['max']
                )
                action = "扩大"
            else:
                new_size = max(
                    self.grid_size * 0.9,  # 缩小10%
                    self.config.GRID_PARAMS['min']
                )
                action = "缩小"
            
            # 建议改进：添加趋势判断
            price_trend = self._get_price_trend()  # 获取价格趋势（1小时）
            if price_trend > 0:  # 上涨趋势
                new_size *= 1.05  # 额外增加5%
            elif price_trend < 0:  # 下跌趋势
                new_size *= 0.95  # 额外减少5%
            
            self.grid_size = new_size
            self.logger.info(
                f"动态调整网格 | 操作: {action} | "
                f"波动率: {volatility:.2%} | "
                f"新尺寸: {self.grid_size}%"
            )

    def _log_order(self, order):
        """记录订单信息"""
        try:
            side = order['side']
            price = float(order['price'])
            amount = float(order['amount'])
            total = price * amount
            
            # 计算利润
            profit = 0
            if side == 'sell':
                # 卖出时计算利润 = 卖出价格 - 基准价格
                profit = (price - self.base_price) * amount
            elif side == 'buy':
                # 买入时利润为0
                profit = 0
            
            # 只在这里添加交易记录
            self.order_tracker.add_trade({
                'timestamp': time.time(),
                'side': side,
                'price': price,
                'amount': amount,
                'profit': profit,
                'order_id': order['id']
            })
            
            # 发送通知
            send_pushplus_message(
                f"网格交易执行通知\n"
                f"交易方向：{'买入' if side == 'buy' else '卖出'}\n"
                f"成交价格：{price}\n"
                f"成交数量：{amount}\n"
                f"交易金额：{total:.2f} USDT\n"
                f"预计利润：{profit:.2f} USDT"
            )
        except Exception as e:
            self.logger.error(f"记录订单失败: {str(e)}")

    async def _reinitialize(self):
        """系统重新初始化"""
        try:
            # 关闭现有连接
            await self.exchange.close()
            
            # 重置关键状态
            self.exchange = ExchangeClient()
            self.order_tracker.reset()
            self.base_price = None
            self.highest = None
            self.lowest = None
            self.grid_size = self.config.GRID_PARAMS['initial']
            self.last_trade = 0
            self.initialized = False  # 确保重置初始化状态
            
            # 等待新的交易所客户端就绪
            await asyncio.sleep(2)
            
            self.logger.info("系统重新初始化完成")
        except Exception as e:
            self.logger.critical(f"重新初始化失败: {str(e)}")
            raise

    async def _check_and_cancel_timeout_orders(self):
        """检查并取消超时订单"""
        current_time = time.time()
        for order_id, timestamp in list(self.order_timestamps.items()):
            if current_time - timestamp > self.ORDER_TIMEOUT:
                try:
                    params = {
                        'timestamp': int(time.time() * 1000 + self.exchange.time_diff),
                        'recvWindow': 5000
                    }
                    order = await self.exchange.fetch_order(order_id, self.config.SYMBOL, params)
                    
                    if order['status'] == 'closed':
                        old_base_price = self.base_price
                        self.base_price = order['price']
                        await self._adjust_grid_after_trade()
                        # 更新最后成交信息
                        self.last_trade_price = order['price']
                        self.last_trade_time = current_time
                        self.logger.info(f"订单已成交 | ID: {order_id} | 价格: {order['price']} | 基准价从 {old_base_price} 更新为 {self.base_price}")
                        # 清除活跃订单标记
                        for side, active_id in self.active_orders.items():
                            if active_id == order_id:
                                self.active_orders[side] = None
                        # 发送成交通知
                        send_pushplus_message(
                            f"BNB {order['side']}单成交\n"
                            f"价格: {order['price']} USDT"
                        )
                    elif order['status'] == 'open':
                        # 取消未成交订单
                        params = {
                            'timestamp': int(time.time() * 1000 + self.exchange.time_diff),
                            'recvWindow': 5000
                        }
                        await self.exchange.cancel_order(order_id, self.config.SYMBOL, params)
                        self.logger.info(f"取消超时订单 | ID: {order_id}")
                        # 清除活跃订单标记
                        for side, active_id in self.active_orders.items():
                            if active_id == order_id:
                                self.active_orders[side] = None
                    
                    # 清理订单记录
                    self.pending_orders.pop(order_id, None)
                    self.order_timestamps.pop(order_id, None)
                except Exception as e:
                    self.logger.error(f"检查订单状态失败: {str(e)} | 订单ID: {order_id}")
                    # 如果是时间同步错误，等待一秒后继续
                    if "Timestamp for this request" in str(e):
                        await asyncio.sleep(1)
                        continue

    async def adjust_grid_size(self):
        """根据波动率和市场趋势调整网格大小"""
        try:
            volatility = await self._calculate_volatility()
            self.logger.info(f"当前波动率: {volatility:.4f}")
            
            # 获取市场趋势
            trend = await self.trend_analyzer.analyze_trend()
            
            # 根据波动率获取基础网格大小
            base_grid = None
            for range_config in self.config.GRID_PARAMS['volatility_threshold']['ranges']:
                if range_config['range'][0] <= volatility < range_config['range'][1]:
                    base_grid = range_config['grid']
                    break
            
            # 根据趋势调整网格
            if trend == 'strong_uptrend':
                new_grid = base_grid * 1.3  # 强上涨趋势扩大30%
                trend_desc = "强上涨趋势，显著扩大网格"
            elif trend == 'weak_uptrend':
                new_grid = base_grid * 1.1  # 弱上涨趋势扩大10%
                trend_desc = "弱上涨趋势，小幅扩大网格"
            elif trend == 'strong_downtrend':
                new_grid = base_grid * 0.7  # 强下跌趋势缩小30%
                trend_desc = "强下跌趋势，显著缩小网格"
            elif trend == 'weak_downtrend':
                new_grid = base_grid * 0.9  # 弱下跌趋势缩小10%
                trend_desc = "弱下跌趋势，小幅缩小网格"
            else:
                new_grid = base_grid  # 震荡市场保持网格
                trend_desc = "震荡市场，保持网格"
            
            # 确保网格在允许范围内
            new_grid = max(min(new_grid, self.config.GRID_PARAMS['max']), self.config.GRID_PARAMS['min'])
            
            if new_grid != self.grid_size:
                self.logger.info(
                    f"调整网格大小 | "
                    f"波动率: {volatility:.2%} | "
                    f"趋势: {trend_desc} | "
                    f"原网格: {self.grid_size:.2f}% | "
                    f"新网格: {new_grid:.2f}%"
                )
                self.grid_size = new_grid
            
        except Exception as e:
            self.logger.error(f"调整网格大小失败: {str(e)}")

    async def _calculate_volatility(self):
        """计算价格波动率"""
        try:
            # 获取24小时K线数据
            klines = await self.exchange.fetch_ohlcv(
                self.config.SYMBOL, 
                timeframe='1h',
                limit=self.config.VOLATILITY_WINDOW
            )
            
            if not klines:
                return 0
                
            # 计算收益率
            prices = [float(k[4]) for k in klines]  # 收盘价
            returns = np.diff(np.log(prices))
            
            # 计算波动率（标准差）并年化
            volatility = np.std(returns) * np.sqrt(24 * 365)  # 年化波动率
            return volatility
            
        except Exception as e:
            self.logger.error(f"计算波动率失败: {str(e)}")
            return 0

    def _adjust_amount_precision(self, amount):
        """根据交易所精度调整数量"""
        precision = 3  # BNB的数量精度是3位小数
        
        formatted_amount = f"{amount:.3f}"
        return float(formatted_amount)

    async def calculate_trade_amount(self, side, order_price):
        # 获取必要参数
        balance = await self.exchange.fetch_balance()
        total_assets = float(balance['total']['USDT']) + float(balance['total'].get('BNB', 0)) * order_price
        
        # 计算波动率调整因子
        volatility = await self._calculate_volatility()
        volatility_factor = 1 / (1 + volatility * 10)  # 波动越大，交易量越小
        
        # 计算凯利仓位
        win_rate = await self.calculate_win_rate()
        payoff_ratio = await self.calculate_payoff_ratio()
        
        # 安全版凯利公式计算
        kelly_f = max(0.0, (win_rate * payoff_ratio - (1 - win_rate)) / payoff_ratio)  # 确保非负
        kelly_f = min(kelly_f, 0.3)  # 最大不超过30%仓位
        
        # 获取价格趋势因子（1小时变化率）
        price_trend = await self._get_price_trend()
        trend_factor = 1 + price_trend * 2  # 趋势强度放大系数设为2
        trend_factor = max(0.5, min(trend_factor, 1.5))  # 限制趋势因子在0.5-1.5之间
        
        # 获取价格分位因子
        price_percentile = await self._get_price_percentile()
        if side == 'buy':
            percentile_factor = 1 + (1 - price_percentile) * 0.5  # 价格越低，买入越多
        else:
            percentile_factor = 1 + price_percentile * 0.5  # 价格越高，卖出越多
        
        # 动态计算交易金额
        risk_adjusted_amount = min(
            total_assets * self.config.RISK_FACTOR * volatility_factor * kelly_f * trend_factor * percentile_factor,
            total_assets * self.config.MAX_POSITION_RATIO
        )
        
        # 应用最小/最大限制
        amount_usdt = max(
            min(risk_adjusted_amount, self.config.BASE_AMOUNT),
            self.config.MIN_TRADE_AMOUNT
        )
        
        return amount_usdt

    async def calculate_win_rate(self):
        """计算胜率"""
        try:
            trades = self.order_tracker.get_trade_history()
            if not trades:
                return 0
            
            # 计算盈利交易数量
            winning_trades = [t for t in trades if t['profit'] > 0]
            win_rate = len(winning_trades) / len(trades)
            
            return win_rate
        except Exception as e:
            self.logger.error(f"计算胜率失败: {str(e)}")
            return 0

    async def calculate_payoff_ratio(self):
        """计算盈亏比"""
        trades = self.order_tracker.get_trade_history()
        if len(trades) < 10:
            return 1.0
        
        avg_win = np.mean([t['profit'] for t in trades if t['profit'] > 0])
        avg_loss = np.mean([abs(t['profit']) for t in trades if t['profit'] < 0])
        return avg_win / avg_loss if avg_loss != 0 else 1.0

    async def _get_price_trend(self):
        """获取价格趋势（基于1小时K线）"""
        try:
            # 获取最近2根1小时K线
            ohlcv = await self.exchange.fetch_ohlcv(self.config.SYMBOL, '1h', limit=2)
            if len(ohlcv) < 2:
                return 0.0
            
            # 计算价格变化率
            prev_close = ohlcv[-2][4]  # 前一根K线收盘价
            current_price = await self._get_latest_price()
            
            # 计算趋势强度
            trend = (current_price - prev_close) / prev_close
            
            # 添加平滑处理
            self.logger.debug(f"价格趋势计算 | 前收盘: {prev_close} | 现价: {current_price} | 趋势: {trend:.2%}")
            return trend
            
        except Exception as e:
            self.logger.error(f"获取价格趋势失败: {str(e)}")
            return 0.0

    async def save_trade_stats(self):
        """保存交易统计数据"""
        stats = {
            'timestamp': datetime.now().isoformat(),
            'grid_size': self.grid_size,
            'position_size': self.current_position,
            'volatility': await self._calculate_volatility(),
            'win_rate': await self.calculate_win_rate(),
            'payoff_ratio': await self.calculate_payoff_ratio()
        }
        with open('trade_stats.json', 'a') as f:
            f.write(json.dumps(stats) + '\n')

    async def _get_order_price(self, side):
        """获取订单价格"""
        try:
            order_book = await self.exchange.fetch_order_book(self.config.SYMBOL)
            ask_price = order_book['asks'][0][0]  # 卖一价
            bid_price = order_book['bids'][0][0]  # 买一价
            
            if side == 'buy':
                order_price = ask_price  # 直接用卖一价
            else:
                order_price = bid_price  # 直接用买一价
            
            order_price = round(order_price, 2)
            
            self.logger.info(
                f"订单定价 | 方向: {side} | "
                f"订单价: {order_price}"
            )
            
            return order_price
        except Exception as e:
            self.logger.error(f"获取订单价格失败: {str(e)}")
            raise

    async def _get_price_percentile(self, period='7d'):
        """获取当前价格在历史中的分位位置"""
        try:
            # 获取过去7天价格数据（使用4小时K线）
            ohlcv = await self.exchange.fetch_ohlcv(self.config.SYMBOL, '4h', limit=42)  # 42根4小时K线 ≈ 7天
            closes = [candle[4] for candle in ohlcv]
            current_price = await self._get_latest_price()
            
            # 计算分位值
            sorted_prices = sorted(closes)
            lower = sorted_prices[int(len(sorted_prices)*0.25)]  # 25%分位
            upper = sorted_prices[int(len(sorted_prices)*0.75)]  # 75%分位
            
            # 添加数据有效性检查
            if len(sorted_prices) < 10:  # 当数据不足时使用更宽松的判断
                self.logger.warning("历史数据不足，使用简化分位计算")
                mid_price = (sorted_prices[0] + sorted_prices[-1]) / 2
                return 0.5 if current_price >= mid_price else 0.0
            
            # 计算当前价格位置
            if current_price <= lower:
                return 0.0  # 处于低位
            elif current_price >= upper:
                return 1.0  # 处于高位
            else:
                return (current_price - lower) / (upper - lower)
            
        except Exception as e:
            self.logger.error(f"获取价格分位失败: {str(e)}")
            return 0.5  # 默认中间位置

    async def _calculate_required_funds(self, side):
        """计算需要划转的资金量"""
        current_price = await self._get_latest_price()
        balance = await self.exchange.fetch_balance()
        total_assets = float(balance['total']['USDT']) + float(balance['total'].get('BNB', 0)) * current_price
        
        # 获取当前订单需要的金额
        amount_usdt = await self.calculate_trade_amount(side, current_price)
        
        # 考虑手续费和滑价
        required = amount_usdt * 1.05  # 增加5%缓冲
        return min(required, self.config.MAX_POSITION_RATIO * total_assets)

    async def _transfer_excess_funds(self):
        """将多余资金转回理财账户"""
        try:
            balance = await self.exchange.fetch_balance()
            current_price = await self._get_latest_price()
            
            # 保留资金 = 最小交易金额 * 2（为了确保有足够资金进行交易）
            keep_amount = self.config.MIN_TRADE_AMOUNT * 2
            
            # 处理USDT
            usdt_balance = float(balance['free'].get('USDT', 0))
            if usdt_balance > keep_amount:
                transfer_amount = usdt_balance - keep_amount
                self.logger.info(f"转移多余USDT到理财: {transfer_amount:.2f}")
                await self.exchange.transfer_to_savings('USDT', transfer_amount)
            
            # 处理BNB，保留等值于MIN_TRADE_AMOUNT的BNB
            min_bnb_hold = keep_amount / current_price
            bnb_balance = float(balance['free'].get('BNB', 0))
            if bnb_balance > min_bnb_hold:
                transfer_amount = bnb_balance - min_bnb_hold
                self.logger.info(f"转移多余BNB到理财: {transfer_amount:.4f}")
                await self.exchange.transfer_to_savings('BNB', transfer_amount)
            
            self.logger.info("多余资金已转移到理财账户")
        except Exception as e:
            self.logger.error(f"转移多余资金失败: {str(e)}")

    async def _check_flip_signal(self):
        """检查是否需要翻转交易方向"""
        try:
            current_price = self.current_price
            price_diff = abs(current_price - self.base_price)
            flip_threshold = self.base_price * FLIP_THRESHOLD(self.grid_size)
            
            if price_diff >= flip_threshold:
                # 智能预划转资金
                await self._pre_transfer_funds(current_price)
                self.logger.info(f"价格偏离阈值 | 当前价: {current_price} | 基准价: {self.base_price}")
                return True
        except Exception as e:
            self.logger.error(f"翻转信号检查失败: {str(e)}")
            return False

    async def _pre_transfer_funds(self, current_price):
        """智能预划转资金"""
        try:
            # 根据预期方向计算需求
            expected_side = 'buy' if current_price > self.base_price else 'sell'
            required = await self._calculate_required_funds(expected_side)
            
            # 添加20%缓冲
            required_with_buffer = required * 1.2
            
            # 分批次划转（应对大额划转限制）
            max_single_transfer = 5000  # 假设单次最大划转5000 USDT
            while required_with_buffer > 0:
                transfer_amount = min(required_with_buffer, max_single_transfer)
                await self.exchange.transfer_to_spot('USDT', transfer_amount)
                required_with_buffer -= transfer_amount
                self.logger.info(f"预划转完成: {transfer_amount} USDT | 剩余需划转: {required_with_buffer}")
                
            self.logger.info("资金预划转完成，等待10秒确保到账")
            await asyncio.sleep(10)  # 等待资金到账
            
        except Exception as e:
            self.logger.error(f"预划转失败: {str(e)}")
            raise

    def _calculate_dynamic_base(self, total_assets):
        """计算动态基础交易金额"""
        # 计算基于总资产百分比的交易金额范围
        min_amount = max(
            self.config.MIN_TRADE_AMOUNT,  # 不低于20 USDT
            total_assets * self.config.MIN_POSITION_PERCENT  # 不低于总资产的5%
        )
        max_amount = total_assets * self.config.MAX_POSITION_PERCENT  # 不超过总资产的15%
        
        # 计算目标交易金额（总资产的10%）
        target_amount = total_assets * 0.1
        
        # 确保交易金额在允许范围内
        return max(
            min_amount,
            min(
                target_amount,
                max_amount
            )
        )

    async def _check_and_transfer_initial_funds(self):
        """检查并划转初始资金"""
        try:
            # 获取现货和理财账户余额
            balance = await self.exchange.fetch_balance()
            funding_balance = await self.exchange.fetch_funding_balance()
            total_assets = await self._get_total_assets()
            current_price = await self._get_latest_price()
            
            # 计算目标持仓（总资产的16%）
            target_usdt = total_assets * 0.16
            target_bnb = (total_assets * 0.16) / current_price
            
            # 获取现货余额
            usdt_balance = float(balance['free'].get('USDT', 0))
            bnb_balance = float(balance['free'].get('BNB', 0))
            
            # 计算总余额（现货+理财）
            total_usdt = usdt_balance + float(funding_balance.get('USDT', 0))
            total_bnb = bnb_balance + float(funding_balance.get('BNB', 0))
            
            # 调整USDT余额
            if usdt_balance > target_usdt:
                # 多余的申购到理财
                transfer_amount = usdt_balance - target_usdt
                self.logger.info(f"发现可划转USDT: {transfer_amount}")
                await self.exchange.transfer_to_savings('USDT', transfer_amount)
            elif usdt_balance < target_usdt:
                # 不足的从理财赎回
                transfer_amount = target_usdt - usdt_balance
                self.logger.info(f"从理财赎回USDT: {transfer_amount}")
                await self.exchange.transfer_to_spot('USDT', transfer_amount)
            
            # 调整BNB余额
            if bnb_balance > target_bnb:
                # 多余的申购到理财
                transfer_amount = bnb_balance - target_bnb
                self.logger.info(f"发现可划转BNB: {transfer_amount}")
                await self.exchange.transfer_to_savings('BNB', transfer_amount)
            elif bnb_balance < target_bnb:
                # 不足的从理财赎回
                transfer_amount = target_bnb - bnb_balance
                self.logger.info(f"从理财赎回BNB: {transfer_amount}")
                await self.exchange.transfer_to_spot('BNB', transfer_amount)
            
            self.logger.info(
                f"资金分配完成\n"
                f"USDT: {total_usdt:.2f}\n"
                f"BNB: {total_bnb:.4f}"
            )
        except Exception as e:
            self.logger.error(f"初始资金检查失败: {str(e)}")

    async def _get_total_assets(self):
        """获取总资产价值（USDT）"""
        try:
            # 使用缓存避免频繁请求
            current_time = time.time()
            if hasattr(self, '_assets_cache') and \
               current_time - self._assets_cache['time'] < 60:  # 1分钟缓存
                return self._assets_cache['value']
            
            balance = await self.exchange.fetch_balance()
            funding_balance = await self.exchange.fetch_funding_balance()
            current_price = await self._get_latest_price()
            
            # 分别获取现货和理财账户余额
            spot_bnb = float(balance['free'].get('BNB', 0) or 0)
            spot_usdt = float(balance['free'].get('USDT', 0) or 0)
            
            # 加上已冻结的余额
            spot_bnb += float(balance['used'].get('BNB', 0) or 0)
            spot_usdt += float(balance['used'].get('USDT', 0) or 0)
            
            # 加上理财账户余额
            fund_bnb = 0
            fund_usdt = 0
            if funding_balance:
                fund_bnb = float(funding_balance.get('BNB', 0) or 0)
                fund_usdt = float(funding_balance.get('USDT', 0) or 0)
            
            # 确保价格有效
            if not current_price or current_price <= 0:
                self.logger.error("获取价格失败，无法计算总资产")
                return self._assets_cache['value'] if hasattr(self, '_assets_cache') else 0
            
            # 分别计算现货和理财账户总值
            spot_value = spot_usdt + (spot_bnb * current_price)
            fund_value = fund_usdt + (fund_bnb * current_price)
            total_assets = spot_value + fund_value
            
            # 更新缓存
            self._assets_cache = {
                'time': current_time,
                'value': total_assets
            }
            
            # 只在资产变化超过1%时才记录日志
            if not hasattr(self, '_last_logged_assets') or \
               abs(total_assets - self._last_logged_assets) / self._last_logged_assets > 0.01:
                self.logger.info(
                    f"总资产: {total_assets:.2f} USDT | "
                    f"现货: {spot_value:.2f} USDT "
                    f"(BNB: {spot_bnb:.4f}, USDT: {spot_usdt:.2f}) | "
                    f"理财: {fund_value:.2f} USDT "
                    f"(BNB: {fund_bnb:.4f}, USDT: {fund_usdt:.2f})"
                )
                self._last_logged_assets = total_assets
            
            return total_assets
            
        except Exception as e:
            self.logger.error(f"计算总资产失败: {str(e)}")
            return self._assets_cache['value'] if hasattr(self, '_assets_cache') else 0

    async def _update_total_assets(self):
        """更新总资产信息"""
        try:
            balance = await self.exchange.fetch_balance()
            funding_balance = await self.exchange.fetch_funding_balance()
            
            # 计算总资产
            bnb_balance = float(balance['total'].get('BNB', 0))
            usdt_balance = float(balance['total'].get('USDT', 0))
            current_price = await self._get_latest_price()
            
            self.total_assets = usdt_balance + (bnb_balance * current_price)
            self.logger.info(f"更新总资产: {self.total_assets:.2f} USDT")
            
        except Exception as e:
            self.logger.error(f"更新总资产失败: {str(e)}")

    async def get_ma_data(self, short_period=20, long_period=50):
        """获取MA数据"""
        try:
            # 获取K线数据
            klines = await self.exchange.fetch_ohlcv(
                self.config.SYMBOL, 
                timeframe='1h',
                limit=long_period + 10  # 多获取一些数据以确保计算准确
            )
            
            if not klines:
                return None, None
            
            # 提取收盘价
            closes = [float(x[4]) for x in klines]
            
            # 计算短期和长期MA
            short_ma = sum(closes[-short_period:]) / short_period
            long_ma = sum(closes[-long_period:]) / long_period
            
            return short_ma, long_ma
            
        except Exception as e:
            self.logger.error(f"获取MA数据失败: {str(e)}")
            return None, None
    
    async def get_macd_data(self):
        """获取MACD数据"""
        try:
            # 获取K线数据
            klines = await self.exchange.fetch_ohlcv(
                self.config.SYMBOL,
                timeframe='1h',
                limit=100  # MACD需要更多数据来计算
            )
            
            if not klines:
                return None, None
            
            # 提取收盘价
            closes = [float(x[4]) for x in klines]
            
            # 计算EMA12和EMA26
            ema12 = self._calculate_ema(closes, 12)
            ema26 = self._calculate_ema(closes, 26)
            
            # 计算MACD线
            macd_line = ema12 - ema26
            
            # 计算信号线（MACD的9日EMA）
            signal_line = self._calculate_ema([macd_line], 9)
            
            return macd_line, signal_line
            
        except Exception as e:
            self.logger.error(f"获取MACD数据失败: {str(e)}")
            return None, None
    
    async def get_adx_data(self, period=14):
        """获取ADX数据"""
        try:
            # 获取K线数据
            klines = await self.exchange.fetch_ohlcv(
                self.config.SYMBOL,
                timeframe='1h',
                limit=period + 10
            )
            
            if not klines:
                return None
            
            # 提取高低收价格
            highs = [float(x[2]) for x in klines]
            lows = [float(x[3]) for x in klines]
            closes = [float(x[4]) for x in klines]
            
            # 计算TR和DM
            tr = []  # True Range
            plus_dm = []  # +DM
            minus_dm = []  # -DM
            
            for i in range(1, len(klines)):
                tr.append(max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i-1]),
                    abs(lows[i] - closes[i-1])
                ))
                
                plus_dm.append(max(0, highs[i] - highs[i-1]))
                minus_dm.append(max(0, lows[i-1] - lows[i]))
            
            # 计算ADX
            atr = sum(tr[-period:]) / period
            plus_di = (sum(plus_dm[-period:]) / period) / atr * 100
            minus_di = (sum(minus_dm[-period:]) / period) / atr * 100
            dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
            adx = sum([dx]) / period  # 简化版ADX计算
            
            return adx
            
        except Exception as e:
            self.logger.error(f"获取ADX数据失败: {str(e)}")
            return None
    
    def _calculate_ema(self, data, period):
        """计算EMA"""
        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema
    
    async def determine_trend(self):
        """综合判断市场趋势"""
        try:
            # 获取各项指标数据
            short_ma, long_ma = await self.get_ma_data()
            macd_line, signal_line = await self.get_macd_data()
            adx = await self.get_adx_data(14)
            
            if None in [short_ma, long_ma, macd_line, signal_line, adx]:
                self.logger.error("获取技术指标数据失败")
                return 'neutral'
            
            # 判断趋势
            ma_trend = 'uptrend' if short_ma > long_ma else 'downtrend'
            macd_trend = 'uptrend' if macd_line > signal_line else 'downtrend'
            trend_strength = 'strong' if adx > 25 else 'weak'
            
            self.logger.info(
                f"趋势分析 | "
                f"MA趋势: {ma_trend} | "
                f"MACD趋势: {macd_trend} | "
                f"ADX: {adx:.2f}"
            )
            
            # 综合判断
            if ma_trend == 'uptrend' and macd_trend == 'uptrend' and trend_strength == 'strong':
                return 'uptrend'
            elif ma_trend == 'downtrend' and macd_trend == 'downtrend' and trend_strength == 'strong':
                return 'downtrend'
            else:
                return 'neutral'
                
        except Exception as e:
            self.logger.error(f"趋势判断失败: {str(e)}")
            return 'neutral'

class TrendAnalyzer:
    def __init__(self, trader):
        self.trader = trader
        self.logger = logging.getLogger(self.__class__.__name__)
        self.last_trend = 'neutral'
        self.trend_start_time = time.time()
        self.trend_signals = []  # 存储最近的趋势信号
        self.signal_window = 6   # 增加到6个信号用于确认
        self.last_log_time = 0   # 上次日志记录时间
        self.log_interval = 300  # 每5分钟记录一次日志
        
    async def analyze_trend(self):
        """分析市场趋势"""
        try:
            current_time = time.time()
            
            # 获取技术指标数据
            short_ma, long_ma = await self.trader.get_ma_data(20, 50)
            macd_line, signal_line = await self.trader.get_macd_data()
            adx = await self.trader.get_adx_data(14)
            
            if None in [short_ma, long_ma, macd_line, signal_line, adx]:
                return self.last_trend
            
            # 计算各个指标的趋势信号
            ma_trend = self._get_ma_trend(short_ma, long_ma)
            macd_trend = self._get_macd_trend(macd_line, signal_line)
            trend_strength = self._get_trend_strength(adx)
            
            # 记录趋势信号
            current_signal = {
                'ma': ma_trend,
                'macd': macd_trend,
                'strength': trend_strength,
                'time': current_time
            }
            self.trend_signals.append(current_signal)
            self.trend_signals = self.trend_signals[-self.signal_window:]  # 保留最近的信号
            
            # 确定当前趋势
            current_trend = self._determine_trend(ma_trend, macd_trend, trend_strength)
            
            # 确认趋势
            confirmed_trend = self._confirm_trend(current_trend)
            
            # 控制日志输出频率
            if current_time - self.last_log_time >= self.log_interval:
                self.logger.info(
                    f"趋势分析 | "
                    f"MA: {ma_trend} | "
                    f"MACD: {macd_trend} | "
                    f"强度: {trend_strength} | "
                    f"确认趋势: {confirmed_trend}"
                )
                self.last_log_time = current_time
            
            return confirmed_trend
            
        except Exception as e:
            self.logger.error(f"趋势分析失败: {str(e)}")
            return 'neutral'
    
    def _get_ma_trend(self, short_ma, long_ma):
        """判断均线趋势"""
        diff_percent = (short_ma - long_ma) / long_ma * 100
        
        if diff_percent > 0.5:  # 短期均线高于长期均线0.5%以上
            return 'strong_up'
        elif diff_percent > 0.1:
            return 'weak_up'
        elif diff_percent < -0.5:
            return 'strong_down'
        elif diff_percent < -0.1:
            return 'weak_down'
        else:
            return 'neutral'
    
    def _get_macd_trend(self, macd_line, signal_line):
        """判断MACD趋势"""
        diff = macd_line - signal_line
        
        if diff > 0.1:  # MACD线显著高于信号线
            return 'strong_up'
        elif diff > 0:
            return 'weak_up'
        elif diff < -0.1:
            return 'strong_down'
        elif diff < 0:
            return 'weak_down'
        else:
            return 'neutral'
    
    def _get_trend_strength(self, adx):
        """判断趋势强度"""
        if adx > 30:
            return 'very_strong'
        elif adx > 25:
            return 'strong'
        elif adx > 20:
            return 'moderate'
        else:
            return 'weak'
    
    def _determine_trend(self, ma_trend, macd_trend, strength):
        """综合判断趋势"""
        if strength in ['very_strong', 'strong']:
            if ma_trend in ['strong_up', 'weak_up'] and macd_trend in ['strong_up', 'weak_up']:
                return 'strong_uptrend'
            elif ma_trend in ['strong_down', 'weak_down'] and macd_trend in ['strong_down', 'weak_down']:
                return 'strong_downtrend'
        elif strength == 'moderate':
            if ma_trend in ['strong_up', 'weak_up'] and macd_trend in ['strong_up', 'weak_up']:
                return 'weak_uptrend'
            elif ma_trend in ['strong_down', 'weak_down'] and macd_trend in ['strong_down', 'weak_down']:
                return 'weak_downtrend'
        
        return 'neutral'
    
    def _confirm_trend(self, current_trend):
        """趋势确认机制"""
        # 如果趋势信号不足，返回中性
        if len(self.trend_signals) < self.signal_window:
            return 'neutral'
        
        # 检查信号的时间跨度是否足够
        oldest_signal_time = self.trend_signals[0]['time']
        newest_signal_time = self.trend_signals[-1]['time']
        if newest_signal_time - oldest_signal_time < 900:  # 至少需要15分钟
            return self.last_trend
        
        # 检查最近的趋势信号是否一致
        trends = [signal['ma'] for signal in self.trend_signals]
        up_count = sum(1 for t in trends if t.endswith('up'))
        down_count = sum(1 for t in trends if t.endswith('down'))
        
        # 需要至少80%的信号一致才确认趋势
        threshold = len(trends) * 0.8
        
        if up_count >= threshold:
            return 'strong_uptrend' if current_trend == 'strong_uptrend' else 'weak_uptrend'
        elif down_count >= threshold:
            return 'strong_downtrend' if current_trend == 'strong_downtrend' else 'weak_downtrend'
        
        # 如果没有明确趋势，保持当前趋势一段时间
        if time.time() - self.trend_start_time < 900:  # 15分钟内保持趋势
            return self.last_trend
        
        return 'neutral'

    # ... 其他方法将在下一部分继续 