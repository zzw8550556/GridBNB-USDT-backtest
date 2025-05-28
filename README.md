# GridBNB-USDT-backtest

本项目实现了基于网格交易策略的币安BNB/USDT历史数据回测系统，支持动态网格调整、风控参数配置，并可视化回测结果。适合量化交易策略研究与测试。

---

## 目录结构

```
.
├── backtest.py                  # 主回测逻辑
├── backtest_visualization.py    # 回测结果可视化
├── config.py                    # 策略参数与风控配置
├── history_kline_downloader.py # Binance期货历史K线数据下载 GUI工具
├── requirements.txt             # 依赖库列表
├── BNBUSDT_BINANCE_2025-01-01_00_00_00_2025-05-19_23_59_59.pkl  # 示例历史数据
└── README.md # 项目说明文档
```

## 环境依赖

请确保已安装 Python 3.7 及以上版本。  
安装依赖库：

```bash
pip install -r requirements.txt
```

## 数据准备

1. **示例数据**  
    项目自带了示例数据文件 `BNBUSDT_BINANCE_2025-01-01_00_00_00_2025-05-19_23_59_59.pkl`，无需额外准备。  
    如需替换为其他数据，请确保数据为 Pandas DataFrame pickle 格式，且包含 `close_price` 列，索引为时间戳。
2. **自己下载数据**  
    可以使用 K 线数据下载 GUI工具`history_kline_downloader.py`自动获取 Binance 期货历史数据。

## 历史K线数据下载

为便于获取最新的历史K线数据，项目提供了基于 Tkinter 的带用户界面的数据下载工具：
   
1. 运行下载工具：
   ```
   python history_kline_downloader.py
   ```
2. 在弹出的窗口中进行如下操作：
   - **代币名称**：例如 `BNBUSDT`  
   - **K线周期**：支持 `1m`, `5m`, `15m`, `30m`, `1h` 等周期  
   - **开始/结束日期**：按照 `YYYY-MM-DD` 格式输入  
   - **保存格式**：选择 `pkl` 或 `csv` 文件格式  
   - **代理设置**（必选）：点击“代理设置”按钮，配置代理地址以便访问 Binance API
3. 点击“下载”按钮开始数据下载，下载进度及日志信息将在窗口中显示。  
4. 下载结束后，文件将自动保存在当前目录，可以直接将下载的数据用于回测。


将 `.env.example` 文件复制为副本，并重命名成`.env`

## 运行回测

在命令行中运行主程序：

```bash
python backtest.py
```

运行后会输出如下统计信息：

- 总交易次数
- 获胜次数
- 年化收益率
- 最大回撤
- 胜率
- 盈亏比
- 最终余额
- 总收益

并弹出回测结果的可视化图表。

## 策略说明

- **网格参数**、**风控参数**等均可在 `config.py` 中自定义。
- 策略支持动态调整网格间距，依据历史波动率和短期趋势自动优化。
- 详细策略逻辑见 `backtest.py` 文件头部注释。

## 可视化

回测结束后会自动弹出净值曲线与交易点位图，便于分析策略表现。

## 常见问题

- 如需自定义数据或参数，请修改 `config.py` 或替换数据文件。
- 若遇到依赖问题，请检查 `requirements.txt` 中的依赖及 Python 环境。

