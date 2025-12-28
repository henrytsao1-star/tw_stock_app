import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import sqlite3
import io
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. 資料庫與基礎設定 ---
DB_NAME = 'stock_history.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scan_results
                 (date TEXT, ticker TEXT, name TEXT, price REAL, gain REAL, days INTEGER, score INTEGER)''')
    conn.commit()
    conn.close()

# --- 2. 核心分析邏輯 ---
def get_all_stock_info():
    urls = {"https://isin.twse.com.tw/isin/C_public.jsp?strMode=2": ".TW",
            "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4": ".TWO"}
    stock_dict = {}
    for url, suffix in urls.items():
        try:
            res = requests.get(url)
            df = pd.read_html(res.text)[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:]
            for val in df['有價證券代號及名稱']:
                if '　' in str(val):
                    ticker, name = str(val).split('　')
                    if len(ticker) == 4 and ticker.isdigit():
                        stock_dict[ticker] = (name, suffix)
        except: continue
    return stock_dict

def analyze_stock(ticker, info, min_gain=10, min_days=4):
    name, suffix = info
    try:
        stock = yf.Ticker(f"{ticker}{suffix}")
        hist = stock.history(period="7mo")
        if len(hist) < 60: return None
        
        recent_34 = hist.tail(34)
        high_p, low_p = recent_34['High'].max(), recent_34['Low'].min()
        gain = (high_p - low_p) / low_p
        if gain < (min_gain / 100): return None
        
        peak_idx = recent_34['High'].argmax()
        days_since_peak = len(recent_34) - 1 - peak_idx
        if days_since_peak < min_days: return None
        
        # 量縮檢查
        peak_loc = hist.index.get_loc(recent_34.index[peak_idx])
        max_vol = hist['Volume'].iloc[max(0, peak_loc-1):peak_loc+2].max()
        if not any(hist['Volume'].tail(3) < (max_vol / 3)): return None
        
        price = hist['Close'].iloc[-1]
        ma5, ma20 = hist['Close'].rolling(5).mean().iloc[-1], hist['Close'].rolling(20).mean().iloc[-1]
        score = 3 if price > ma5 > ma20 else (2 if price > ma5 else 0)
        if score == 0: return None

        return (ticker, name, round(price, 2), round(gain*100, 2), days_since_peak, score)
    except: return None

# --- 3. 自動化排程執行函數 ---
def run_automated_scan():
    init_db()
    print(f"[{datetime.now()}] 啟動自動排程掃描...")
    stock_info = get_all_stock_info()
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(analyze_stock, t, info) for t, info in stock_info.items()]
        for f in futures:
            res = f.result()
            if res: results.append(res)
    
    if results:
        df = pd.DataFrame(results, columns=['ticker', 'name', 'price', 'gain', 'days', 'score'])
        date_str = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_NAME)
        conn.execute("DELETE FROM scan_results WHERE date=?", (date_str,))
        df['date'] = date_str
        df.to_sql('scan_results', conn, if_exists='append', index=False)
        conn.commit()
        conn.close()
        print(f"掃描完成，已儲存 {len(results)} 筆資料。")

# --- 4. Streamlit 網頁介面 ---
def run_streamlit_app():
    st.title("📈 天選強勢整理股系統")
    tab1, tab2 = st.tabs(["今日掃描", "歷史 7 日紀錄"])
    
    with tab1:
        if st.button("開始全台股分析"):
            run_automated_scan()
            st.success("分析完成！資料已存入資料庫。")
            
    with tab2:
        conn = sqlite3.connect(DB_NAME)
        try:
            history_df = pd.read_sql("SELECT * FROM scan_results ORDER BY date DESC", conn)
            if not history_df.empty:
                for d in history_df['date'].unique()[:7]:
                    with st.expander(f"📅 報告日期：{d}"):
                        day_data = history_df[history_df['date'] == d]
                        st.dataframe(day_data)
            else: st.info("尚無歷史資料。")
        except: st.info("資料庫讀取中...")
        finally: conn.close()

# --- 5. 程式入口判斷 ---
if __name__ == "__main__":
    if "--scheduled" in sys.argv:
        run_automated_scan()
    else:
        run_streamlit_app()