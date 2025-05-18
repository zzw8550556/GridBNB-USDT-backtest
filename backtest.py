import pandas as pd
import numpy as np
import logging
from config import TradingConfig, FLIP_THRESHOLD, MIN_TRADE_AMOUNT, POSITION_SCALE_FACTOR, MIN_POSITION_PERCENT, MAX_POSITION_PERCENT, INITIAL_BASE_PRICE, VOLATILITY_WINDOW ,INITIAL_PRINCIPAL
from backtest_visualization import plot_backtest_results_period
def read_pkl_data(pkl_file):
    """
    根据文件名读取 pickle 数据
    """
    return pd.read_pickle(pkl_file)

def calculate_trade_amount(total_assets):
    """
    根据配置中的 POSITION_SCALE_FACTOR 和 MIN/MAX_POSITION_PERCENT 计算下单金额
    """
    desired = total_assets * POSITION_SCALE_FACTOR
    # 限制下单金额在总资产的 MIN_POSITION_PERCENT 与 MAX_POSITION_PERCENT 之间
    lower_bound = total_assets * MIN_POSITION_PERCENT
    upper_bound = total_assets * MAX_POSITION_PERCENT
    amount = max(desired, lower_bound)
    amount = min(amount, upper_bound)
    # 同时确保不低于配置的最低交易金额
    return max(amount, MIN_TRADE_AMOUNT)

def backtest_(df, initial_balance=INITIAL_PRINCIPAL):
    """
    模拟网格交易策略回测，融入 config.py 中定义的交易参数和风控逻辑：
    
    1. 初始化：
       - 若配置中指定 INITIAL_BASE_PRICE（非0），则采用其作为基准价，否则用第一根K线收盘价。
       - 当前网格值取自 TradingConfig.GRID_PARAMS['initial']（单位为百分比），转换为小数后作为 grid_pct。
    
    2. 买入信号（空仓状态）：
       - 当价格跌破下边界（current_base_price*(1 - grid_pct)）时启动买入监控，记录最低价。
       - 当价格从最低价反弹达到最低价 + (current_base_price*grid_pct)*FLIP_THRESHOLD(当前网格值)时，
         动态计算下单金额（基于当前总资产和配置的 POSITION_SCALE_FACTOR 等）后执行买入操作。
    
    3. 卖出信号（持仓状态）：
       - 当价格上穿上边界（current_base_price*(1 + grid_pct)）时启动卖出监控，记录期间最高价。
       - 当价格从最高点回落超过 (current_base_price*grid_pct)*FLIP_THRESHOLD(当前网格值)时卖出持仓，
         并使用卖出价更新基准价。
    
    4. 动态网格调整：
       - 卖出成交后，若历史数据足够（至少 VOLATILITY_WINDOW 小时对应的分钟数），
         计算最近波动率 = (窗口内最高价 - 最低价)/current_base_price。
       - 根据 TradingConfig.GRID_PARAMS['volatility_threshold'] 中各区间，确定新的网格值；
         再根据与上一根K线比较的短期趋势修正（上升则×1.05，下降则×0.95），
         并限制在 TradingConfig.GRID_PARAMS['min'] 与 TradingConfig.GRID_PARAMS['max'] 范围内，
         最终更新 grid_pct（= new_grid_value/100）。
    
    5. 每个时点记录账户组合净值（现金余额+持仓估值）以及成交记录，最终输出统计数据及CSV文件。
    """
    results = []
    trades = []
    
    df = df.sort_index()  # 确保按时间顺序
    prices = df['close_price'].values
    times = df.index

    # 初始化基准价：若 config 中 INITIAL_BASE_PRICE 非0，则使用之
    current_base_price = INITIAL_BASE_PRICE if INITIAL_BASE_PRICE > 0 else df.iloc[0]['close_price']
    # 当前网格百分比取自配置（单位百分比），转换成小数
    current_grid_value = TradingConfig.GRID_PARAMS['initial']  # 例如 2.0 表示2%
    current_grid_pct = current_grid_value / 100.0

    # 记录网格允许的下限与上限（单位为百分比）
    grid_min = TradingConfig.GRID_PARAMS['min']
    grid_max = TradingConfig.GRID_PARAMS['max']
    
    # 状态标识：'flat'为空仓，'long'为持仓状态
    state = 'flat'
    buy_monitoring = False   # 买入监控状态标识
    buy_min_price = None     # 买入监控时记录的最低价
    sell_monitoring = False  # 卖出监控状态标识
    sell_max_price = None    # 卖出监控时记录的最高价
    open_position = None     # 当前持仓信息，若有持仓则为字典（买入时间、价格、数量）
    trade_count = 0
    current_balance = initial_balance

    # 对于波动率计算，将 VOLATILITY_WINDOW (单位小时) 换算为对应的K线数量（假设1分钟一根）
    bars_for_vol = int(VOLATILITY_WINDOW * 60)

    for i, current_time in enumerate(times):
        price = prices[i]
        # 持仓按当前价格估值
        position_value = open_position['units'] * price if (state == 'long' and open_position) else 0.0
        portfolio_value = current_balance + position_value
        results.append({
            'datetime': current_time,
            'balance': portfolio_value
        })

        # 空仓状态监控买入信号
        if state == 'flat':
            next_buy_level = current_base_price * (1 - current_grid_pct)
            if not buy_monitoring and price <= next_buy_level:
                buy_monitoring = True
                buy_min_price = price
            if buy_monitoring:
                # 更新监控期间的最低价
                buy_min_price = min(buy_min_price, price)
                # 计算翻转阈值（绝对价格差）：依据当前基准价和网格
                grid_step_val = current_base_price * current_grid_pct
                threshold = grid_step_val * FLIP_THRESHOLD(current_grid_value)
                if price >= buy_min_price + threshold:
                    # 动态计算下单金额
                    trade_amount = calculate_trade_amount(portfolio_value)
                    if current_balance >= trade_amount:
                        units = trade_amount / price
                        open_position = {
                            'buy_time': current_time,
                            'buy_price': price,
                            'units': units
                        }
                        current_balance -= trade_amount  # 扣除买入金额
                        state = 'long'
                        buy_monitoring = False  # 重置买入监控
        # 持仓状态监控卖出信号
        elif state == 'long' and open_position:
            upper_band = current_base_price * (1 + current_grid_pct)
            if not sell_monitoring and price >= upper_band:
                sell_monitoring = True
                sell_max_price = price
            if sell_monitoring:
                sell_max_price = max(sell_max_price, price)
                grid_step_val = current_base_price * current_grid_pct
                threshold = grid_step_val * FLIP_THRESHOLD(current_grid_value)
                if price <= sell_max_price - threshold:
                    exit_price = price
                    profit_trade = open_position['units'] * (exit_price - open_position['buy_price'])
                    current_balance += open_position['units'] * exit_price
                    trades.append({
                        'entry_datetime': open_position['buy_time'],
                        'exit_datetime': current_time,
                        'entry_price': open_position['buy_price'],
                        'exit_price': exit_price,
                        'profit': profit_trade
                    })
                    # 卖出后，用成交价更新基准价
                    current_base_price = exit_price
                    trade_count += 1
                    
                    # 动态网格调整：若历史数据足够，则计算过去 bars_for_vol 根K线的波动率
                    if i >= bars_for_vol:
                        window_prices = prices[i - bars_for_vol + 1: i + 1]
                        window_max = np.max(window_prices)
                        window_min = np.min(window_prices)
                        volatility = (window_max - window_min) / current_base_price  # 以基准价归一化
                        # 根据配置中波动率区间确定新的网格值（单位百分比）
                        new_grid_value = current_grid_value  # 默认保持不变
                        for rng in TradingConfig.GRID_PARAMS['volatility_threshold']['ranges']:
                            low, high = rng['range']
                            if low <= volatility < high:
                                new_grid_value = rng['grid']
                                break
                        # 修正短期趋势：比较当前价与上一根K线价格
                        if i > 0:
                            prev_price = prices[i-1]
                            trend = (price - prev_price) / prev_price
                            if trend > 0:
                                new_grid_value = min(new_grid_value * 1.05, grid_max)
                            elif trend < 0:
                                new_grid_value = max(new_grid_value * 0.95, grid_min)
                        current_grid_value = new_grid_value
                        current_grid_pct = current_grid_value / 100.0
                        logging.info(f"动态调整网格：新网格值={current_grid_value}%, 波动率={volatility:.4f}")
                    
                    # 卖出后重置状态
                    state = 'flat'
                    sell_monitoring = False
                    open_position = None

    total_trades = len(trades)
    winning_trades = sum(1 for trade in trades if trade['profit'] > 0)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    final_balance = portfolio_value
    profit = final_balance - initial_balance
    
    stats = {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'win_rate': win_rate,
        'final_balance': final_balance,
        'profit': profit
    }
    
    results_df = pd.DataFrame(results)
    trades_df = pd.DataFrame(trades)
    return results_df, trades_df, stats

if __name__ == "__main__":
    pkl_file = "BNBUSDT_BINANCE_2025-01-01_00_00_00_2025-05-19_23_59_59.pkl"
    df = read_pkl_data(pkl_file)
    results_df, trades_df, stats = backtest_(df)
    
    print("\n策略统计:")
    print(f"总交易次数: {stats['total_trades']}")
    print(f"获胜次数: {stats['winning_trades']}")
    print(f"胜率: {stats['win_rate']:.2%}")
    print(f"最终余额: {stats['final_balance']:.2f}")
    print(f"总收益: {stats['profit']:.2f}")

    # 将 'datetime' 转换为 datetime 类型，将 'datetime' 列设置为索引
    results_df['datetime'] = pd.to_datetime(results_df['datetime'])
    trades_df['datetime'] = pd.to_datetime(trades_df['exit_datetime'])
    results_df.set_index('datetime', inplace=True)
    trades_df.set_index('datetime', inplace=True)
    
    plot_backtest_results_period(results_df, trades_df, '4h')  # 每4小时一个点
