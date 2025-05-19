import pandas as pd
import numpy as np
import logging
from tqdm import tqdm
from datetime import datetime
from config import TradingConfig, FLIP_THRESHOLD, MIN_TRADE_AMOUNT, MIN_POSITION_PERCENT, MAX_POSITION_PERCENT, INITIAL_BASE_PRICE, VOLATILITY_WINDOW, INITIAL_PRINCIPAL
from backtest_visualization import plot_backtest_results_period

logging.basicConfig(
    level=logging.INFO,  # 设置日志级别为INFO
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler()]
)

def read_pkl_data(pkl_file):
    """
    根据文件名读取 pickle 数据
    """
    return pd.read_pickle(pkl_file)

# 使用 trader 中的交易金额计算逻辑
def calculate_trade_amount(total_assets, side, order_price, trades, volatility):
    import numpy as np
    # 根据波动率计算调整因子：波动越大，下单金额越小
    volatility_factor = 1 / (1 + volatility * 10)
    # 计算历史交易的胜率与盈亏比，若无历史交易则默认取中性值
    if trades:
        win_trades = [t for t in trades if t['profit'] > 0]
        win_rate = len(win_trades) / len(trades) if trades else 0.5
        avg_win = np.mean([t['profit'] for t in trades if t['profit'] > 0]) if win_trades else 0
        losses = [abs(t['profit']) for t in trades if t['profit'] < 0]
        avg_loss = np.mean(losses) if losses else 1
        payoff_ratio = avg_win / avg_loss if avg_loss != 0 else 1.0
    else:
        win_rate = 0.5
        payoff_ratio = 1.0
    # 安全版凯利公式计算仓位（最大不超过30%）
    kelly_f = max(0.0, (win_rate * payoff_ratio - (1 - win_rate)) / payoff_ratio)
    kelly_f = min(kelly_f, 0.3)
    # 使用中性价格分位（此处缺乏真实历史分位，因此默认取0.5）
    price_percentile = 0.5
    if side == 'buy':
        percentile_factor = 1 + (1 - price_percentile) * 0.5
    else:
        percentile_factor = 1 + price_percentile * 0.5
    # 使用配置中的风险参数进行计算
    risk_factor = TradingConfig.RISK_FACTOR
    max_position_ratio = TradingConfig.MAX_POSITION_RATIO
    base_amount = TradingConfig.BASE_AMOUNT
    min_trade_amount_val = MIN_TRADE_AMOUNT
    risk_adjusted_amount = min(total_assets * risk_factor * volatility_factor * kelly_f * percentile_factor, total_assets * max_position_ratio)
    amount_usdt = max(min(risk_adjusted_amount, base_amount), min_trade_amount_val)
    return amount_usdt

#定义计算动态间隔秒数的函数
def calculate_dynamic_interval(volatility):
    params = TradingConfig.DYNAMIC_INTERVAL_PARAMS
    interval_rules = params['volatility_to_interval_hours']
    default_interval_hours = params.get('default_interval_hours', 1.0)
    matched_interval_hours = default_interval_hours
    for rule in interval_rules:
        low, high = rule['range']
        if low <= volatility < high:
            matched_interval_hours = rule['interval_hours']
            break
    interval_seconds = matched_interval_hours * 3600
    min_interval_seconds = 5 * 60  # 最小间隔5分钟
    return max(interval_seconds, min_interval_seconds)

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

    5. 风险管理检查：
       - 计算当前仓位比例（持仓价值/总资产），如果低于MIN_POSITION_PERCENT或高于MAX_POSITION_PERCENT，则记录日志（类似于risk_manager中的警告）。
    
    6. S1策略逻辑：
       - 利用最近一天（例如1440个数据点，如果假设1分钟一根K线）计算当天的最高价和最低价，
         然后根据配置中定义的S1目标（S1_SELL_TARGET_PCT和S1_BUY_TARGET_PCT，默认分别为50%和70%）判断：
       - 如果处于持仓状态且当前价格突破当天最高且仓位比例超过S1_SELL_TARGET_PCT，则按超出部分卖出一定比例以降低仓位；
       - 如果价格低于当天最低且仓位比例低于S1_BUY_TARGET_PCT，则尝试买入补仓。
    
    7. 每个时点记录账户组合净值（现金余额+持仓估值）以及成交记录，最终输出统计数据。
    """
    results = []
    trades = []
    
    df = df.sort_index()  # 确保按时间顺序
    prices = df['close_price'].values
    times = df.index

    # 初始化基准价：若配置中指定 INITIAL_BASE_PRICE（非0），则采用其作为基准价，否则用第一根K线收盘价。
    current_base_price = INITIAL_BASE_PRICE if INITIAL_BASE_PRICE > 0 else df.iloc[0]['close_price']
    # 当前网格值取自配置（单位百分比），转换为小数
    current_grid_value = TradingConfig.GRID_PARAMS['initial']  # 例如 2.0 表示2%
    current_grid_pct = current_grid_value / 100.0
    
    # 记录上一次网格调整的时间，初始取第一根K线的时间
    last_grid_adjust_time = times[0]
    # 新增：定期重置基准价的逻辑
    reset_interval_seconds = TradingConfig.RESET_INTERVAL_SECONDS if hasattr(TradingConfig, 'RESET_INTERVAL_SECONDS') else 86400  # 默认一天重置一次
    last_reset_time_dt = datetime.strptime(times[0], "%Y-%m-%d %H:%M:%S")

    # 状态标识：'flat'为空仓，'long'为持仓状态
    state = 'flat'
    buy_monitoring = False   # 买入监控状态
    buy_min_price = None     # 监控期间最低价
    sell_monitoring = False  # 卖出监控状态
    sell_max_price = None    # 监控期间最高价
    open_position = None     # 当前持仓信息
    trade_count = 0
    current_balance = initial_balance

    # 对于波动率计算，将 VOLATILITY_WINDOW (单位小时) 换算为对应的分钟数（假设1分钟一根K线）
    bars_for_vol = int(VOLATILITY_WINDOW * 60)

    # 初始化 S1 策略相关变量（采用昨日日线数据）：
    last_day = None              # 上一交易日日期
    curr_day_high = None         # 当天最高价
    curr_day_low = None          # 当天最低价
    s1_daily_high = None         # 昨日最高价（S1参考）
    s1_daily_low = None          # 昨日最低价（S1参考）
    # 获取 S1 参数（若配置中未设置则默认50%卖、70%买）
    S1_SELL_TARGET_PCT = getattr(TradingConfig, 'S1_SELL_TARGET_PCT', 0.50)
    S1_BUY_TARGET_PCT = getattr(TradingConfig, 'S1_BUY_TARGET_PCT', 0.70)

    for i, current_time in enumerate(tqdm(times, desc="回测进度")):
        price = prices[i]
        # 更新当天最高和最低价格，用于 S1 策略参考
        # current_time 是字符串，先转为 datetime 对象
        current_time_dt = datetime.strptime(current_time, "%Y-%m-%d %H:%M:%S")

        # 新增：每隔固定时间间隔重置基准价
        if (current_time_dt - last_reset_time_dt).total_seconds() >= reset_interval_seconds:
            current_base_price = price  # 用当前价格重置基准价
            last_reset_time_dt = current_time_dt
            #logging.info(f"定时重置基准价: 在 {current_time} 重置为 {price:.2f}")
        
        current_date = current_time_dt.date()
        if last_day is None:
            last_day = current_date
            curr_day_high = price
            curr_day_low = price
        elif current_date == last_day:
            curr_day_high = max(curr_day_high, price)
            curr_day_low = min(curr_day_low, price)
        else:
            # 跨日：将上一交易日的最高/最低作为 S1 参考
            s1_daily_high = curr_day_high
            s1_daily_low = curr_day_low
            last_day = current_date
            curr_day_high = price
            curr_day_low = price

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
                # 更新监控期间最低价
                buy_min_price = min(buy_min_price, price)
                # 依据当前基准价和网格计算差额及翻转阈值
                grid_step_val = current_base_price * current_grid_pct
                threshold = grid_step_val * FLIP_THRESHOLD(current_grid_value)
                if price >= buy_min_price + threshold:
                    # 使用新的交易金额计算函数；若无足够波动率样本，则设 volatility=0
                    vol_for_trade = 0
                    if i >= bars_for_vol:
                        window_prices = prices[i - bars_for_vol + 1: i+1]
                        returns = np.diff(np.log(window_prices))
                        vol_for_trade = np.std(returns) * np.sqrt(1440 * 365)
                    trade_amount = calculate_trade_amount(portfolio_value, 'buy', price, trades, vol_for_trade)
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
                    
                    # 动态网格调整
                    if i >= bars_for_vol:
                        window_prices = prices[i - bars_for_vol + 1: i+1]
                        returns = np.diff(np.log(window_prices))
                        volatility = np.std(returns) * np.sqrt(1440 * 365)
                        dynamic_interval = calculate_dynamic_interval(volatility)
                        current_time_dt = datetime.strptime(current_time, "%Y-%m-%d %H:%M:%S")
                        last_grid_adjust_time_dt = datetime.strptime(last_grid_adjust_time, "%Y-%m-%d %H:%M:%S")
                        time_since_last_adjust = (current_time_dt - last_grid_adjust_time_dt).total_seconds()
                        if time_since_last_adjust >= dynamic_interval:
                            # 根据波动率区间获取基础网格
                            base_grid = None
                            for range_config in TradingConfig.GRID_PARAMS['volatility_threshold']['ranges']:
                                low, high = range_config['range']
                                if low <= volatility < high:
                                    base_grid = range_config['grid']
                                    break
                            # 匹配不到则用初始网格
                            if base_grid is None:
                                base_grid = TradingConfig.GRID_PARAMS['initial']
                            # 删除趋势调整，直接用base_grid
                            new_grid_value = base_grid
                            # 限定在[min, max]
                            new_grid_value = max(min(new_grid_value, TradingConfig.GRID_PARAMS['max']), TradingConfig.GRID_PARAMS['min'])
                            # 日志输出
                            logging.info(f"调整网格大小 | 波动率: {volatility:.2%} | 原网格: {current_grid_value:.2f}% | 新网格: {new_grid_value:.2f}%")
                            # 更新
                            current_grid_value = new_grid_value
                            current_grid_pct = current_grid_value / 100.0
                            last_grid_adjust_time = current_time
                    
                    # 卖出后重置状态
                    state = 'flat'
                    sell_monitoring = False
                    open_position = None

        # 风险管理检查：计算当前仓位比例
        position_value = open_position['units'] * price if (state == 'long' and open_position) else 0.0
        portfolio_value = current_balance + position_value
        position_ratio = position_value / portfolio_value if portfolio_value > 0 else 0.0

        if position_ratio < MIN_POSITION_PERCENT:
            pass
            # 可在此记录低仓位警告
        if position_ratio > MAX_POSITION_PERCENT:
            pass
            # 可在此记录仓位过高警告

        # S1策略逻辑：使用昨日日线的高低作为参考进行仓位调整
        if s1_daily_high is not None and s1_daily_low is not None:
            # S1卖出调整：若持仓且当前价突破昨日最高且仓位比例超过S1_SELL_TARGET_PCT，则卖出多余部分
            if state == 'long' and price > s1_daily_high and position_ratio > S1_SELL_TARGET_PCT:
                desired_value = portfolio_value * S1_SELL_TARGET_PCT
                excess_value = position_value - desired_value
                if excess_value >= MIN_TRADE_AMOUNT:
                    sell_units = excess_value / price
                    profit_trade = sell_units * (price - open_position['buy_price'])
                    current_balance += sell_units * price
                    open_position['units'] -= sell_units
                    if open_position['units'] < 1e-8:
                        open_position = None
                        state = 'flat'
                    trade_count += 1
                    trades.append({
                        'entry_datetime': open_position['buy_time'] if open_position else current_time,
                        'exit_datetime': current_time,
                        'entry_price': open_position['buy_price'] if open_position else price,
                        'exit_price': price,
                        'profit': profit_trade,
                        's1': True
                    })
                    logging.info(f"S1卖出调整：卖出 {sell_units:.4f} 单位，剩余仓位 {open_position['units'] if open_position else 0:.4f}")

            # S1买入调整：当价格低于昨日最低且仓位比例低于S1_BUY_TARGET_PCT时，补仓
            if price < s1_daily_low and position_ratio < S1_BUY_TARGET_PCT:
                desired_value = portfolio_value * S1_BUY_TARGET_PCT
                shortage_value = desired_value - position_value
                if shortage_value >= MIN_TRADE_AMOUNT and current_balance >= shortage_value:
                    buy_units = shortage_value / price
                    if state == 'flat':
                        open_position = {
                            'buy_time': current_time,
                            'buy_price': price,
                            'units': buy_units
                        }
                        state = 'long'
                    else:
                        open_position['units'] += buy_units
                    current_balance -= shortage_value
                    trade_count += 1
                    trades.append({
                        'entry_datetime': current_time,
                        'exit_datetime': current_time,
                        'entry_price': price,
                        'exit_price': price,
                        'profit': 0,
                        's1': True
                    })
                    logging.info(f"S1买入调整：买入 {buy_units:.4f} 单位，新仓位 {open_position['units']:.4f}")

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

    # 保存交易记录
    trades_df.to_csv('trades_results.csv')

    # 将 'datetime' 转换为 datetime 类型，并设置为索引
    results_df['datetime'] = pd.to_datetime(results_df['datetime'])
    trades_df['datetime'] = pd.to_datetime(trades_df['exit_datetime'])
    results_df.set_index('datetime', inplace=True)
    trades_df.set_index('datetime', inplace=True)
    
    plot_backtest_results_period(results_df, trades_df, '4h')  # 每4小时一个点