import pandas as pd
import matplotlib.pyplot as plt

def plot_backtest_results_period(results_df: pd.DataFrame, trades_df: pd.DataFrame, resample_freq='1h'):
    """绘制回测结果图表"""
    plt.figure(figsize=(15, 8))

    # 对资金数据进行重采样，比如每小时一个点
    results_resampled = results_df.resample(resample_freq).last()
    
    # 使用重采样后的数据绘制资金曲线
    plt.plot(results_resampled.index, results_resampled['balance'], label='Balance')
    
    plt.title('Backtest Results')
    plt.xlabel('Date')
    plt.ylabel('Balance')
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    
