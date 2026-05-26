"""最小可用版：获取个股日K数据并打印"""
import akshare as ak
import time

end_date = "20260526"
start_date = "20250526"

for attempt in range(3):
    try:
        df = ak.stock_zh_a_hist(
            symbol="300502", period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        print(f"获取到 {len(df)} 条数据")
        print(df.tail())
        break
    except Exception as e:
        print(f"第 {attempt + 1} 次失败: {e}")
        if attempt < 2:
            wait = (attempt + 1) * 5
            print(f"等待 {wait} 秒后重试...")
            time.sleep(wait)