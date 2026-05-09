# -*- coding: utf-8 -*-
"""
腾讯财经行情刷新 v3 - 字段映射已验证
[3]=最新价, [32]=涨跌幅%, [6]=成交量(手), [37]=成交额(万元), [44]=总市值(亿元)
"""
import json, requests, time
from datetime import datetime

DATA_JS_PATH = r"D:\21210\华泰财富研究-openclaw\js_stock_tracker\data.js"

def load():
    with open(DATA_JS_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    s = content.find('window.__STOCK_DATA__ = ') + len('window.__STOCK_DATA__ = ')
    e = len(content)
    for i in range(len(content)-1, s, -1):
        if content[i] == ';': e = i; break
    return json.loads(content[s:e])

def fetch(codes):
    prefixed = ','.join([(f"sh{c}" if c[0] in '69' else f"sz{c}") for c in codes])
    try:
        resp = requests.get(f"https://qt.gtimg.cn/q={prefixed}", timeout=30)
        resp.encoding = 'gbk'
        quotes = {}
        for line in resp.text.strip().split(';'):
            line = line.strip()
            if 'v_' not in line: continue
            parts = line.split('="')
            if len(parts) != 2: continue
            code = parts[0].replace('v_','').replace('sh','').replace('sz','')
            f = parts[1].rstrip('"').split('~')
            if len(f) < 46:
                continue
            try:
                quotes[code] = {
                    'price': float(f[3]) or 0,
                    'change_pct': float(f[32]) or 0,
                    'volume': float(f[6]) * 100 if f[6] else 0,
                    'turnover': float(f[37]) * 10000 if f[37] else 0,  # 万元->元
                    'market_cap': float(f[44]) if f[44] else 0,  # 亿元
                }
            except (ValueError, IndexError):
                continue
        return quotes
    except Exception as e:
        print(f'Error: {e}')
        return {}

def save(data, count):
    today = datetime.now()
    if today.weekday() == 5: today = today.replace(day=today.day-1)
    elif today.weekday() == 6: today = today.replace(day=today.day-2)
    date_str = today.strftime('%Y-%m-%d')
    data['date'] = date_str
    if 'daily_summary' in data:
        data['daily_summary']['date'] = date_str
        # 重新计算涨跌统计
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
    print("腾讯财经行情刷新 v3")
    data = load()
    stocks = data.get('stocks', [])
    codes = [s['code'] for s in stocks if s.get('code')]
    print(f"共 {len(codes)} 只股票")

    all_q = {}
    bs = 300
    for i in range(0, len(codes), bs):
        batch = codes[i:i+bs]
        n = i//bs + 1
        total = (len(codes)-1)//bs + 1
        print(f"  批次 {n}/{total}: {len(batch)} 只", flush=True)
        q = fetch(batch)
        all_q.update(q)
        if i + bs < len(codes): time.sleep(0.3)

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
