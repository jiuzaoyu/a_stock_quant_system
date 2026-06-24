"""天天基金 API 配置：接口地址、请求头、采集参数。"""

# ---- 目标基金类型（用于过滤全量基金列表）----
TARGET_FUND_TYPE_PREFIXES = ("股票型", "混合型", "指数型")

# ---- HTTP 请求头 ----
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
}

HEADERS_FUND = {
    **HEADERS_BASE,
    "Referer": "https://fund.eastmoney.com/",
}

HEADERS_F10 = {
    **HEADERS_BASE,
    "Referer": "https://fundf10.eastmoney.com/",
}

# ---- API 地址 ----
FUND_LIST_URL = "http://fund.eastmoney.com/js/fundcode_search.js"
FUND_HISTORY_TPL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
FUND_HOLDINGS_URL = (
    "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    "?type=jjcc&code={code}&topline=10&year=&month=&rt=0.1"
)

# ---- 采集参数 ----
REQUEST_TIMEOUT = 30
REQUEST_DELAY_SECONDS = 0.5
MAX_RETRIES = 3
CONCURRENCY = 10
PROGRESS_EVERY = 20
LOOKBACK_YEARS = 2
