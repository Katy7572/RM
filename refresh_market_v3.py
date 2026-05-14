# -*- coding: utf-8 -*-
"""
全A股行情刷新 - 使用 akshare (东方财富数据源)
替换原腾讯财经API，解决GitHub Actions上网络不稳定的问题
"""
import json, sys, time
from datetime import datetime
from pathlib import Path

try:
    import akshare as ak
except ImportError:
    print("请先安装 akshare: pip install akshare")
    sys.exit(1)

_script_dir = Path(__file__).resolve().parent
DATA_JS_PATH = _script_dir / "data.js" if (_script_dir / "data.js").exists() else _script_dir.parent / "data.js"


def load():
    with open(DATA_JS_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    s = content.find('window.__STOCK_DATA__ = ') + len('window.__STOCK_DATA__ = ')
    e = len(content)
    for i in range(len(content)-1, s, -1):
        if content[i] == ';': e = i; break
    return json.loads(content[s:e])


def fetch_all_quotes():
    """从东方财富拉取全A股实时行情"""
    print("  正在拉取全A股行情数据...")
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            print("  ERROR: akshare 返回空数据")
            return {}
        print(f"  拉取到 {len(df)} 条行情")
        quotes = {}
        for _, row in df.iterrows():
            code = str(row.get('代码', '')).strip()
            if not code:
                continue
            # 统一去除 .SH/.SZ/.BJ 后缀
            clean_code = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            try:
                quotes[clean_code] = {
                    'price': float(row.get('最新价', 0)) or 0,
                    'change_pct': float(row.get('涨跌幅', 0)) or 0,
                    'volume': float(row.get('成交量', 0)) or 0,  # 手
                    'turnover': float(row.get('成交额', 0)) or 0,  # 元
                    'market_cap': float(row.get('总市值', 0)) or 0,  # 亿元
                }
            except (ValueError, TypeError):
                continue
        return quotes
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}


def save(data, count):
    today = datetime.now()
    if today.weekday() == 5: today = today.replace(day=today.day-1)
    elif today.weekday() == 6: today = today.replace(day=today.day-2)
    date_str = today.strftime('%Y-%m-%d')
    data['date'] = date_str
    if 'daily_summary' in data:
        data['daily_summary']['date'] = date_str
        stocks = data.get('stocks', [])
        data['daily_summary']['total_stocks'] = len(stocks)
        data['daily_summary']['up_count'] = sum(1 for s in stocks if s.get('change_pct', 0) > 0)
        data['daily_summary']['down_count'] = sum(1 for s in stocks if s.get('change_pct', 0) < 0)
        data['daily_summary']['flat_count'] = sum(1 for s in stocks if s.get('change_pct', 0) == 0)
    with open(DATA_JS_PATH, 'w', encoding='utf-8') as f:
        f.write(f"// 股票数据 - 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"window.__STOCK_DATA__ = {json.dumps(data, ensure_ascii=False)};\n")
    return count


def main():
    print("全A股行情刷新 (akshare/东方财富)")
    data = load()
    stocks = data.get('stocks', [])
    print(f"共 {len(stocks)} 只股票")

    # 拉取全A股行情
    all_q = fetch_all_quotes()
    if not all_q:
        print("行情数据拉取失败，保持原有数据不变")
        sys.exit(1)

    upd = 0
    for s in stocks:
        q = all_q.get(s['code'])
        if q:
            s['price'] = q['price']
            s['change_pct'] = q['change_pct']
            s['volume'] = q['volume']
            s['turnover'] = q['turnover']
            s['market_cap'] = q['market_cap']
            upd += 1

    save(data, upd)
    print(f"\n完成! 更新 {upd}/{len(stocks)} 只, 日期 {data['date']}")


if __name__ == '__main__':
    main()
