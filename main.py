import asyncio
import logging
import traceback
import platform
import sys
from trader import GridTrader
from helpers import LogConfig, send_pushplus_message
from web_server import start_web_server
from exchange_client import ExchangeClient
from config import TradingConfig

# 在Windows平台上设置SelectorEventLoop
if platform.system() == 'Windows':
    import asyncio
    # 在Windows平台上强制使用SelectorEventLoop
    if sys.version_info[0] == 3 and sys.version_info[1] >= 8:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logging.info("已设置Windows SelectorEventLoop策略")

async def main():
    try:
        # 初始化统一日志配置
        LogConfig.setup_logger()
        logging.info("="*50)
        logging.info("网格交易系统启动")
        logging.info("="*50)
        
        # 创建交易所客户端和配置实例
        exchange = ExchangeClient()
        config = TradingConfig()
        
        # 使用正确的参数初始化交易器
        trader = GridTrader(exchange, config)
        
        # 初始化交易器
        await trader.initialize()
        
        # 启动Web服务器
        web_server_task = asyncio.create_task(start_web_server(trader))
        
        # 启动交易循环
        trading_task = asyncio.create_task(trader.main_loop())
        
        # 等待所有任务完成
        await asyncio.gather(web_server_task, trading_task)
        
    except Exception as e:
        error_msg = f"启动失败: {str(e)}\n{traceback.format_exc()}"
        logging.error(error_msg)
        send_pushplus_message(error_msg, "致命错误")
        
    finally:
        if 'trader' in locals():
            try:
                await trader.exchange.close()
                logging.info("交易所连接已关闭")
            except Exception as e:
                logging.error(f"关闭连接时发生错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 