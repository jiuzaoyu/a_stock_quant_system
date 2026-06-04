"""
TA-Lib 技术指标测试脚本。

用法: python tests/talibAPI/test_indicators.py
"""
import talib
import pandas as pd
import sqlite3

# 从 SQLite 数据库读取股票数据
conn = sqlite3.connect('data/stock_daily.db')
df = pd.read_sql(
    "SELECT * FROM daily WHERE ts_code='000001.SZ' ORDER BY trade_date",
    conn, parse_dates=['trade_date']
)
conn.close()
df.set_index('trade_date', inplace=True)

# === 趋势指标 ===
# 简单移动平均线
df['SMA_5'] = talib.SMA(df['close'], timeperiod=5)
df['SMA_20'] = talib.SMA(df['close'], timeperiod=20)

# 指数移动平均线
df['EMA_12'] = talib.EMA(df['close'], timeperiod=12)
df['EMA_26'] = talib.EMA(df['close'], timeperiod=26)

# MACD
df['MACD'], df['MACD_signal'], df['MACD_hist'] = talib.MACD(
    df['close'],
    fastperiod=12, slowperiod=26, signalperiod=9
)

# 布林带
df['BB_upper'], df['BB_mid'], df['BB_lower'] = talib.BBANDS(
    df['close'], timeperiod=20, nbdevup=2, nbdevdn=2
)

# ADX(平均趋向指数)
df['ADX'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)

# === 动量指标 ===
# RSI
df['RSI_14'] = talib.RSI(df['close'], timeperiod=14)

# KDJ(通过STOCH实现)
df['K'], df['D'] = talib.STOCH(
    df['high'], df['low'], df['close'],
    fastk_period=9, slowk_period=3, slowd_period=3
)
df['J'] = 3 * df['K'] - 2 * df['D']

# CCI
df['CCI'] = talib.CCI(df['high'], df['low'], df['close'], timeperiod=14)

# Williams %R
df['WILLR'] = talib.WILLR(df['high'], df['low'], df['close'], timeperiod=14)

# === 成交量指标 ===
# OBV
df['OBV'] = talib.OBV(df['close'], df['vol'])

print(df[['close', 'SMA_20', 'MACD', 'RSI_14', 'K', 'D', 'OBV']].tail(10))
