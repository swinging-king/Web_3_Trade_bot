import requests
import time
import hmac
import hashlib
import pandas as pd
import numpy as np
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_URL = "https://mock-api.roostoo.com"
API_KEY = "E9rT5yUiP1oA7sDdF3gJ9hKlZ0xC4vBnM6qW2eRtY8uI1oPaS5dF7gHjK2lL0ZxC"
SECRET_KEY = "E1rT3yUiP5oA7sDdF9gJ1hKlZ3xC5vBnM7qW9eRtY1uI3oPaS5dF7gHjK9lL"

# 交易配置
SELECTED_ASSETS = ['XRP/USD', 'TRX/USD', 'BNB/USD', 'BTC/USD', 'ETH/USD']

# 最小交易金額配置
MIN_ORDER_AMOUNTS = {
    'BNB/USD': 1.0,
    'BTC/USD': 1.0,  
    'ETH/USD': 1.0,
    'XRP/USD': 1,
    'TRX/USD': 10
}

def get_timestamp():
    return str(int(time.time() * 1000))

def create_signature(secret_key, params):
    sorted_params = sorted(params.items())
    query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature, query_string

class EnhancedAutoTrader:
    def __init__(self):
        self.positions = {}
        self.trade_count = 0
        self.last_request_time = 0
        
        # 技術指標數據框架
        self.priceDF = pd.DataFrame(columns=SELECTED_ASSETS)
        self.changeDF = pd.DataFrame(columns=SELECTED_ASSETS)
        self.short_MA_DF = pd.DataFrame(columns=SELECTED_ASSETS)
        self.long_MA_DF = pd.DataFrame(columns=SELECTED_ASSETS)
        
        # 風險管理參數
        self.max_position_size = 10.0  # 最大持倉金額(USD)
        self.stop_loss_pct = 0.02      # 2% 止損
        self.take_profit_pct = 0.03    # 3% 止盈
        self.max_drawdown_pct = 0.05   # 5% 最大回撤
        
        # 多策略參數
        self.rsi_period = 14
        self.volume_period = 20
        
    def _rate_limit(self):
        """速率限制控制"""
        current_time = time.time()
        if self.last_request_time > 0:
            elapsed = current_time - self.last_request_time
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)
        self.last_request_time = time.time()
        
    def get_ticker_data(self):
        """獲取市場數據"""
        self._rate_limit()
        
        url = f"{BASE_URL}/v3/ticker"
        params = {'timestamp': get_timestamp()}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('Success'):
                    return data.get('Data', {})
            else:
                logging.warning(f"獲取行情失敗: {response.status_code}")
        except Exception as e:
            logging.error(f"行情請求異常: {e}")
            
        return None
    
    def place_order(self, pair, side, quantity):
        """下單函數"""
        self._rate_limit()
        
        params = {
            'pair': pair,
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': str(quantity),
            'timestamp': get_timestamp()
        }
        
        signature, query_string = create_signature(SECRET_KEY, params)
        
        headers = {
            'RST-API-KEY': API_KEY,
            'MSG-SIGNATURE': signature,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        url = f"{BASE_URL}/v3/place_order"
        
        try:
            logging.info(f"📤 下單: {side} {quantity} {pair}")
            response = requests.post(url, headers=headers, data=query_string, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('Success'):
                    order_detail = result.get('OrderDetail', {})
                    filled_price = float(order_detail.get('FilledAverPrice', 0))
                    logging.info(f"✅ 下單成功! 訂單ID: {order_detail.get('OrderID')}")
                    logging.info(f"   成交價格: {filled_price}")
                    return True, order_detail, filled_price
                else:
                    error_msg = result.get('ErrMsg', 'Unknown error')
                    logging.error(f"❌ 下單失敗: {error_msg}")
                    return False, error_msg, 0
            else:
                logging.error(f"❌ HTTP錯誤: {response.status_code} - {response.text}")
                return False, f"HTTP {response.status_code}", 0
                
        except Exception as e:
            logging.error(f"❌ 下單異常: {e}")
            return False, str(e), 0
    
    def calculate_order_quantity(self, pair, price, amount_usd=2.0):
        """計算訂單數量"""
        # 風險管理：檢查總持倉
        total_position_value = self.calculate_total_position_value()
        if total_position_value >= self.max_position_size:
            logging.warning(f"⚠️ 達到最大持倉限制: {total_position_value:.2f} USD")
            return 0
            
        if pair in MIN_ORDER_AMOUNTS:
            min_amount = MIN_ORDER_AMOUNTS[pair]
            if isinstance(min_amount, int):
                quantity = max(min_amount, int(amount_usd / price))
            else:
                quantity = amount_usd / price
                if amount_usd < min_amount:
                    quantity = min_amount / price
                    logging.info(f"⚠️ 調整數量以滿足最小訂單要求: {min_amount} USD")
        else:
            quantity = amount_usd / price
            
        if 'XRP' in pair or 'TRX' in pair:
            quantity = int(quantity)
        else:
            quantity = round(quantity, 6)
            
        return quantity
    
    def calculate_total_position_value(self):
        """計算總持倉價值"""
        total_value = 0
        market_data = self.get_ticker_data()
        if not market_data:
            return total_value
            
        for asset, position in self.positions.items():
            if asset in market_data:
                current_price = float(market_data[asset].get('LastPrice', 0))
                total_value += position['quantity'] * current_price
                
        return total_value
    
    def update_technical_data(self):
        """更新技術指標數據"""
        market_data = self.get_ticker_data()
        if not market_data:
            return False
            
        # 更新價格數據
        price_data = {}
        change_data = {}
        for asset in SELECTED_ASSETS:
            if asset in market_data:
                asset_data = market_data[asset]
                last_price = float(asset_data.get('LastPrice', 0))
                prev_price = float(asset_data.get('MinAsk', last_price))
                
                price_data[asset] = last_price
                
                if prev_price > 0:
                    change_pct = (last_price / prev_price - 1) * 100
                else:
                    change_pct = 0
                change_data[asset] = change_pct
            else:
                price_data[asset] = 0
                change_data[asset] = 0
        
        # 更新DataFrame
        price_row = pd.DataFrame([price_data], columns=SELECTED_ASSETS)
        self.priceDF = pd.concat([self.priceDF, price_row], ignore_index=True)
        
        change_row = pd.DataFrame([change_data], columns=SELECTED_ASSETS)
        self.changeDF = pd.concat([self.changeDF, change_row], ignore_index=True)
        
        # 計算技術指標
        if len(self.priceDF) >= 20:
            self._calculate_technical_indicators()
            return True
            
        return False
    
    def _calculate_technical_indicators(self):
        """計算多種技術指標"""
        # 移動平均線
        short_data = {}
        long_data = {}
        rsi_data = {}
        
        for asset in SELECTED_ASSETS:
            prices = self.priceDF[asset]
            
            # 短期MA (10期)
            if len(prices) >= 10:
                short_ma = prices.iloc[-10:].mean()
            else:
                short_ma = prices.mean() if len(prices) > 0 else 0
            short_data[asset] = short_ma
            
            # 長期MA (20期)
            if len(prices) >= 20:
                long_ma = prices.iloc[-20:].mean()
            else:
                long_ma = prices.mean() if len(prices) > 0 else 0
            long_data[asset] = long_ma
            
            # RSI計算
            if len(prices) >= self.rsi_period + 1:
                rsi = self._calculate_rsi(prices, self.rsi_period)
                rsi_data[asset] = rsi
            else:
                rsi_data[asset] = 50
        
        # 更新DataFrame
        short_row = pd.DataFrame([short_data], columns=SELECTED_ASSETS)
        self.short_MA_DF = pd.concat([self.short_MA_DF, short_row], ignore_index=True)
        
        long_row = pd.DataFrame([long_data], columns=SELECTED_ASSETS)
        self.long_MA_DF = pd.concat([self.long_MA_DF, long_row], ignore_index=True)
    
    def _calculate_rsi(self, prices, period):
        """計算RSI指標"""
        if len(prices) < period + 1:
            return 50
            
        deltas = prices.diff()
        gains = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        losses = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        
        if losses.iloc[-1] == 0:
            return 100 if gains.iloc[-1] != 0 else 50
            
        rs = gains.iloc[-1] / losses.iloc[-1]
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def check_trading_signals(self):
        """檢查多策略交易信號"""
        if len(self.short_MA_DF) < 2 or len(self.long_MA_DF) < 2:
            return [], []
            
        buy_signals = []
        sell_signals = []
        
        market_data = self.get_ticker_data()
        if not market_data:
            return buy_signals, sell_signals
        
        for asset in SELECTED_ASSETS:
            if asset not in market_data:
                continue
                
            current_price = float(market_data[asset].get('LastPrice', 0))
            current_short = self.short_MA_DF[asset].iloc[-1]
            current_long = self.long_MA_DF[asset].iloc[-1]
            prev_short = self.short_MA_DF[asset].iloc[-2] if len(self.short_MA_DF) >= 2 else current_short
            prev_long = self.long_MA_DF[asset].iloc[-2] if len(self.long_MA_DF) >= 2 else current_long
            
            # 策略1: 移動平均線交叉
            ma_signal = 0
            if prev_short <= prev_long and current_short > current_long:
                ma_signal = 1  # 黃金交叉
            elif prev_short >= prev_long and current_short < current_long:
                ma_signal = -1  # 死亡交叉
            
            # 策略2: 價格突破
            breakout_signal = 0
            if len(self.priceDF) >= 20:
                resistance = self.priceDF[asset].iloc[-20:].max()
                support = self.priceDF[asset].iloc[-20:].min()
                
                if current_price > resistance:
                    breakout_signal = 1
                elif current_price < support:
                    breakout_signal = -1
            
            # 策略3: RSI超買超賣
            rsi_signal = 0
            if hasattr(self, 'rsi_data') and asset in self.rsi_data:
                rsi = self.rsi_data[asset]
                if rsi < 30:  # 超賣
                    rsi_signal = 1
                elif rsi > 70:  # 超買
                    rsi_signal = -1
            
            # 綜合信號評分
            total_score = ma_signal + breakout_signal + rsi_signal
            
            # 買入信號
            if total_score >= 2 and asset not in self.positions:
                buy_signals.append(asset)
                logging.info(f"💰 綜合買入信號: {asset} (評分: {total_score})")
                
            # 賣出信號
            elif total_score <= -2 and asset in self.positions:
                sell_signals.append(asset)
                logging.info(f"💸 綜合賣出信號: {asset} (評分: {total_score})")
        
        return buy_signals, sell_signals
    
    def check_risk_management(self):
        """風險管理檢查"""
        sell_signals = []
        market_data = self.get_ticker_data()
        if not market_data:
            return sell_signals
            
        for asset, position in list(self.positions.items()):
            if asset in market_data:
                current_price = float(market_data[asset].get('LastPrice', 0))
                entry_price = position['entry_price']
                
                # 計算盈虧
                if entry_price > 0:
                    pnl_pct = (current_price - entry_price) / entry_price
                    
                    # 止損檢查
                    if pnl_pct <= -self.stop_loss_pct:
                        sell_signals.append(asset)
                        logging.warning(f"🛑 止損觸發: {asset} (虧損: {pnl_pct:.2%})")
                    
                    # 止盈檢查
                    elif pnl_pct >= self.take_profit_pct:
                        sell_signals.append(asset)
                        logging.info(f"🎯 止盈觸發: {asset} (盈利: {pnl_pct:.2%})")
        
        return sell_signals
    
    def execute_trading_strategy(self, buy_signals, sell_signals):
        """執行交易策略"""
        market_data = self.get_ticker_data()
        if not market_data:
            return
            
        # 執行買入
        for asset in buy_signals:
            if asset in market_data:
                asset_data = market_data[asset]
                current_price = float(asset_data.get('LastPrice', 0))
                
                if current_price > 0:
                    quantity = self.calculate_order_quantity(asset, current_price, amount_usd=2.0)
                    
                    if quantity > 0:
                        success, result, filled_price = self.place_order(asset, "BUY", quantity)
                        if success and filled_price > 0:
                            self.positions[asset] = {
                                'quantity': quantity,
                                'entry_price': filled_price,  # 使用實際成交價
                                'entry_time': datetime.now(),
                                'order_id': result.get('OrderID')
                            }
                            logging.info(f"✅ 買入持倉: {asset} @ {filled_price}")
        
        # 執行賣出
        for asset in sell_signals:
            if asset in self.positions:
                position = self.positions[asset]
                quantity = position['quantity']
                
                success, result, filled_price = self.place_order(asset, "SELL", quantity)
                if success and filled_price > 0:
                    entry_price = position['entry_price']
                    
                    # 檢查賣出價格是否高於成本
                    if entry_price > 0:
                        pnl = (filled_price - entry_price) / entry_price
                        if filled_price > entry_price:
                            logging.info(f"📈 盈利交易 - {asset}: +{pnl:.2%}")
                            logging.info(f"   買入價: {entry_price}, 賣出價: {filled_price}")
                        else:
                            logging.warning(f"📉 虧損交易 - {asset}: {pnl:.2%}")
                            logging.info(f"   買入價: {entry_price}, 賣出價: {filled_price}")
                    
                    del self.positions[asset]
    
    def run(self):
        """主交易循環"""
        logging.info("🚀 啟動增強版自動交易機器人")
        logging.info("📊 支持的交易對: XRP/USD, TRX/USD, BNB/USD, BTC/USD, ETH/USD")
        logging.info("⚡ 策略: 移動平均線 + 突破 + RSI")
        logging.info("🛡️ 風險管理: 止損2% / 止盈3%")
        
        # 初始化數據
        logging.info("📈 收集初始技術數據...")
        for i in range(20):
            if self.update_technical_data():
                logging.info(f"  數據收集 {i+1}/20")
            time.sleep(1)
        
        logging.info("🔄 開始自動交易循環...")
        
        while True:
            try:
                # 更新技術數據
                if self.update_technical_data():
                    # 檢查交易信號
                    buy_signals, strategy_sell_signals = self.check_trading_signals()
                    
                    # 檢查風險管理信號
                    risk_sell_signals = self.check_risk_management()
                    
                    # 合併賣出信號
                    all_sell_signals = list(set(strategy_sell_signals + risk_sell_signals))
                    
                    # 執行交易
                    if buy_signals or all_sell_signals:
                        self.execute_trading_strategy(buy_signals, all_sell_signals)
                
                # 狀態報告
                self.trade_count += 1
                if self.trade_count % 10 == 0:
                    total_value = self.calculate_total_position_value()
                    logging.info(f"📊 系統狀態 - 循環: {self.trade_count}, 持倉: {len(self.positions)}, 總價值: {total_value:.2f} USD")
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                logging.info("🛑 用戶手動停止")
                break
            except Exception as e:
                logging.error(f"❌ 系統錯誤: {e}")
                time.sleep(30)

if __name__ == "__main__":
    trader = EnhancedAutoTrader()
    trader.run()
