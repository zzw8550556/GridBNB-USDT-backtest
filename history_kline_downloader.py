#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
自动下载 Binance 期货历史 K 线数据并保存为 CSV 或 PKL

功能说明：
1. 使用 binance-futures-connector 库调用接口下载数据。
2. 日期范围、代币（symbol）、周期（interval）等参数均通过 tkinter 界面输入。
3. 下载时使用循环调用接口（参考 query_history 逻辑）获取多天数据，并通过进度条显示下载进度。
4. 下载完成后自动保存数据到当前目录，支持 CSV 或 PKL 格式。
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import pandas as pd
from datetime import datetime, timedelta
import time
import os

# 导入 binance-futures-connector 库
from binance.um_futures import UMFutures

class KlineDownloaderApp:
    def __init__(self, master):
        self.master = master
        master.title("K线数据下载器")
        master.configure(bg="#f0f0f0")  # 设置背景色
        master.resizable(False, False)  # 禁止调整窗口大小
        
        # 创建主框架
        main_frame = ttk.Frame(master, padding="10 10 10 10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 创建输入框架
        input_frame = ttk.LabelFrame(main_frame, text="参数设置", padding="10 10 10 10")
        input_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        
        # 代币名称输入
        ttk.Label(input_frame, text="代币名称:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.symbol_entry = ttk.Entry(input_frame, width=20)
        self.symbol_entry.insert(0, "BNBUSDT")
        self.symbol_entry.grid(row=0, column=1, padx=5, pady=5)
        
        # K线周期选择
        ttk.Label(input_frame, text="K线周期:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.interval_var = tk.StringVar()
        self.interval_combo = ttk.Combobox(input_frame, textvariable=self.interval_var, width=18)
        self.interval_combo['values'] = ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w")
        self.interval_combo.current(0)
        self.interval_combo.grid(row=1, column=1, padx=5, pady=5)
        
        # 开始日期输入框
        ttk.Label(input_frame, text="开始日期 (YYYY-MM-DD):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.start_date_entry = ttk.Entry(input_frame, width=20)
        self.start_date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.start_date_entry.grid(row=2, column=1, padx=5, pady=5)
        
        # 结束日期输入框
        ttk.Label(input_frame, text="结束日期 (YYYY-MM-DD):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.end_date_entry = ttk.Entry(input_frame, width=20)
        self.end_date_entry.insert(0, (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
        self.end_date_entry.grid(row=3, column=1, padx=5, pady=5)
        
        # 保存格式选择（CSV 或 PKL）
        ttk.Label(input_frame, text="保存格式:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        self.save_format_var = tk.StringVar()
        self.save_format_combo = ttk.Combobox(input_frame, textvariable=self.save_format_var, width=18)
        self.save_format_combo['values'] = ("pkl","csv")
        self.save_format_combo.current(0)
        self.save_format_combo.grid(row=4, column=1, padx=5, pady=5)
        
        # 下载按钮
        self.download_button = ttk.Button(input_frame, text="下载", command=self.start_download, style="Accent.TButton")
        self.download_button.grid(row=5, column=0, columnspan=1, pady=20)
        
        # 代理设置按钮
        self.proxy_button = ttk.Button(input_frame, text="代理设置", command=self.open_proxy_window, style="Accent.TButton")
        self.proxy_button.grid(row=5, column=1, columnspan=2, pady=10)
        
        # 创建日志框架
        log_frame = ttk.LabelFrame(main_frame, text="下载日志", padding="10 10 10 10")
        log_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        
        # 日志文本框
        self.log_text = scrolledtext.ScrolledText(log_frame, width=50, height=10, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.log_text.config(state=tk.DISABLED)  # 设置为只读
        
        # 进度条框架
        progress_frame = ttk.Frame(main_frame, padding="5 5 5 5")
        progress_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=5, pady=5)
        
        # 进度条
        ttk.Label(progress_frame, text="下载进度:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.progress = ttk.Progressbar(progress_frame, orient="horizontal", length=300, mode="determinate")
        self.progress.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        self.progress["value"] = 0
        
        # 设置样式
        style = ttk.Style()
        style.configure("TLabel", font=("Arial", 10))
        style.configure("TButton", font=("Arial", 10))
        style.configure("Accent.TButton", font=("Arial", 10, "bold"))
        
        # 初始化 Binance Futures 客户端
        self.proxies = { 'https': 'http://127.0.0.1:10808' }
        self.client = UMFutures(proxies=self.proxies)
        
        # 添加日志
        self.add_log("程序已启动，请设置参数并点击下载按钮开始下载数据。")

    #代理设置弹窗
    def open_proxy_window(self):
        proxy_win = tk.Toplevel(self.master)
        proxy_win.title("代理设置")
        proxy_win.resizable(False, False)
        ttk.Label(proxy_win, text="代理地址:").grid(row=0, column=0, padx=10, pady=10)
        proxy_var = tk.StringVar(value=self.proxies.get('https', ''))
        proxy_entry = ttk.Entry(proxy_win, textvariable=proxy_var, width=30)
        proxy_entry.grid(row=0, column=1, padx=10, pady=10)

        def save_proxy():
            proxy_addr = proxy_var.get().strip()
            self.proxies['https'] = proxy_addr
            self.client = UMFutures(proxies=self.proxies)
            self.add_log(f"已设置代理: {proxy_addr}")
            proxy_win.destroy()

        save_btn = ttk.Button(proxy_win, text="保存", command=save_proxy)
        save_btn.grid(row=1, column=0, columnspan=2, pady=10)

        proxy_win.grab_set()  # 模态

    def add_log(self, message):
        """
        向日志框添加消息
        """
        self.log_text.config(state=tk.NORMAL)
        current_time = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{current_time}] {message}\n")
        self.log_text.see(tk.END)  # 滚动到最新消息
        self.log_text.config(state=tk.DISABLED)
        self.master.update_idletasks()

    def start_download(self):
        """
        验证输入，并启动下载任务线程
        """
        symbol = self.symbol_entry.get().upper().strip()
        interval = self.interval_var.get().strip()
        start_date_str = self.start_date_entry.get().strip()
        end_date_str = self.end_date_entry.get().strip()
        save_format = self.save_format_var.get().strip()

        # 日期格式校验
        try:
            start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        except Exception as e:
            self.show_error("日期格式错误")
            return

        if start_dt >= end_dt:
            self.show_error("开始日期必须早于结束日期")
            return

        # 禁用下载按钮，避免重复点击
        self.download_button.config(state="disabled")
        self.add_log(f"开始下载 {symbol} 的 {interval} K线数据，时间范围: {start_date_str} 至 {end_date_str}")
        
        # 启动后台线程执行下载任务，避免界面卡顿
        threading.Thread(target=self.download_klines, args=(symbol, interval, start_dt, end_dt, save_format)).start()

    def download_klines(self, symbol, interval, start_dt, end_dt, save_format):
        """
        循环下载历史数据：
        - 以 startTime 为入口，循环调用接口，每次下载一片段数据；
        - 根据返回数据更新当前下载进度，当不足 limit 条数据时认为已下载完
        - 最后将所有数据转为 DataFrame 并调用保存函数
        """
        all_data = []
        # 每次请求数据数量，根据需要可调整（适配大周期时建议减小该值）
        limit = 900  
        current_start = start_dt
        start_timestamp = start_dt.timestamp()
        end_timestamp = end_dt.timestamp()
        total_duration = end_timestamp - start_timestamp
        # 根据周期字符串获取时间差
        interval_delta = self.get_interval_delta(interval)
        
        batch_count = 0

        while current_start < end_dt:
            batch_count += 1
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "startTime": int(current_start.timestamp() * 1000),
                "endTime": int(end_dt.timestamp() * 1000)
            }
            try:
                self.add_log(f"正在下载第 {batch_count} 批数据...")
                klines = self.client.klines(**params)
                time.sleep(0.25)
                self.add_log(f"成功获取 {len(klines)} 条K线数据")
            except Exception as e:
                error_msg = f"请求错误：{str(e)}"
                self.add_log(error_msg)
                self.show_error(error_msg)
                break

            if not klines:
                self.add_log("未获取到数据，下载完成")
                break

            all_data.extend(klines)
            # 取本次返回数据的最后一条，更新下载起始时间（加一个周期间隔，避免重复）
            last_time = int(klines[-1][0]) / 1000  # 转换为秒
            current_start = datetime.fromtimestamp(last_time) + interval_delta
            
            # 计算当前下载的时间范围
            current_time_str = datetime.fromtimestamp(last_time).strftime("%Y-%m-%d %H:%M:%S")
            self.add_log(f"当前下载至: {current_time_str}")

            # 计算进度百分比
            progress_percent = ((last_time - start_timestamp) / total_duration) * 100
            progress_percent = min(100, progress_percent)
            self.update_progress(progress_percent)

            # 如果返回数据少于 limit，则认为数据已全部下载完毕
            if len(klines) < limit:
                self.add_log("数据下载完成")
                break

        # 数据下载完成后转为 DataFrame
        if all_data:
            self.add_log(f"共下载 {len(all_data)} 条K线数据，正在处理...")
            df = pd.DataFrame(all_data, columns=[
                'open_time', 'open_price', 'high_price', 'low_price', 'close_price', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
                'taker_buy_quote_volume', 'ignore'
            ])
            # 转换时间戳
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['open_time'] = df['open_time'].dt.tz_localize('UTC').dt.tz_convert('Asia/Shanghai')
            # 转换数值类型
            for col in ['open_price', 'high_price', 'low_price', 'close_price', 'volume']:
                df[col] = df[col].astype(float)
            # 调用保存函数
            self.add_log("数据处理完成，准备保存...")
            self.master.after(0, self.save_file, df, save_format, symbol, start_dt, end_dt)
        else:
            self.add_log("未获取到任何数据！")
            self.show_error("未获取到任何数据！")
        # 下载完毕后，重新启用下载按钮
        self.master.after(0, lambda: self.download_button.config(state="normal"))

    def get_interval_delta(self, interval):
        """
        根据周期字符串返回对应的 timedelta 对象，支持 'm', 'h', 'd' 单位
        """
        if interval.endswith("m"):
            try:
                minutes = int(interval[:-1])
                return timedelta(minutes=minutes)
            except:
                return timedelta(minutes=1)
        elif interval.endswith("h"):
            try:
                hours = int(interval[:-1])
                return timedelta(hours=hours)
            except:
                return timedelta(hours=1)
        elif interval.endswith("d"):
            try:
                days = int(interval[:-1])
                return timedelta(days=days)
            except:
                return timedelta(days=1)
        elif interval.endswith("w"):
            try:
                weeks = int(interval[:-1])
                return timedelta(weeks=weeks)
            except:
                return timedelta(weeks=1)
        else:
            # 默认1分钟
            return timedelta(minutes=1)

    def update_progress(self, value):
        """
        安全地更新进度条，使用 after 方法切换到主线程执行
        """
        self.master.after(0, self._update_progress, value)

    def _update_progress(self, value):
        self.progress["value"] = value
        self.master.update_idletasks()

    def save_file(self, df, save_format, symbol, start_dt, end_dt):
        """
        直接保存文件到当前目录，按指定格式自动命名
        """
        # 格式化日期时间字符串
        start_datetime = start_dt.strftime("%Y-%m-%d_%H_%M_%S")
        end_datetime = end_dt.strftime("%Y-%m-%d_%H_%M_%S")
        exchange = "BINANCE"  # 交易所名称
        
        # 构建文件名
        filename = f"{symbol}_{exchange}_{start_datetime}_{end_datetime}"
        
        if save_format == "csv":
            file_path = os.path.join(os.getcwd(), f"{filename}.csv")
            try:
                self.add_log(f"正在保存CSV文件到: {file_path}")
                df.to_csv(file_path, index=False)
                self.add_log("CSV文件保存成功")
            except Exception as e:
                error_msg = f"保存CSV时错误：{str(e)}"
                self.add_log(error_msg)
                self.show_error(error_msg)
                return
        else:  # pkl
            file_path = os.path.join(os.getcwd(), f"{filename}.pkl")
            try:
                self.add_log(f"正在保存PKL文件到: {file_path}")
                df.to_pickle(file_path)
                self.add_log("PKL文件保存成功")
            except Exception as e:
                error_msg = f"保存PKL时错误：{str(e)}"
                self.add_log(error_msg)
                self.show_error(error_msg)
                return
        
        # 显示完成消息
        messagebox.showinfo("完成", f"数据下载并保存成功！\n文件路径: {file_path}")

    def show_error(self, message):
        """
        弹出错误提示框
        """
        self.master.after(0, lambda: messagebox.showerror("错误", message))


if __name__ == "__main__":
    root = tk.Tk()
    app = KlineDownloaderApp(root)
    root.mainloop()