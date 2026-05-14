# -*- coding: utf-8 -*-
"""
全A股行情刷新 - akshare 主源 + 腾讯财经降级
GitHub Actions 海外 IP 可能被东方财富风控，用腾讯财经作降级保证可用性
"""
import json, sys, time
from datetime import datetime
from pathlib import Path

try:
    import akshare as ak
    import requests
except ImportError:
    print("请先安装依赖: pip install akshare requests")
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


def fetch_via_akshare():
    """主源：akshare 东方财富"""
    for attempt in range(1, 4):
        print(f"  [akshare] 拉取全A股行情... (尝试 {attempt}/3)")
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                if attempt < 3:
                    time.sleep(5 * attempt)
                    continue
                return None
            print(f"  [akshare] 成功, {len(df)} 条")
            quotes = {}
            for _, row in df.iterrows():
                code = str(row.get('代码', '')).strip().replace('.SH','').replace('.SZ','').replace('.BJ','')
                if not code: continue
                try:
                    quotes[code] = {
                        'price': float(row.get('最新价', 0)) or 0,
                        'change_pct': float(row.get('涨跌幅', 0)) or 0,
                        'volume': float(row.get('成交量', 0)) or 0,
                        'turnover': float(row.get('成交额', 0)) or 0,
                        'market_cap': float(row.get('总市值', 0)) or 0,
                    }
                except (ValueError, TypeError):
                    continue
            return quotes
        except Exception as e:
            print(f"  [akshare] 失败: {e}")
            if attempt < 3:
                time.sleep(5 * attempt)
    return None


def fetch_via_tencent(codes):
    """降级源：腾讯财经批量拉取"""
    # 腾讯API只支持20~30个/次, 分80只一批保证稳定
    BATCH = 80
    quotes = {}
    total = len(codes)
    for i in range(0, total, BATCH):
        batch = codes[i:i+BATCH]
        # sh/sz/bj 前缀
        symbol_list = []
        for c in batch:
            if c.startswith('6') or c.startswith('9'):
                symbol_list.append(f'sh{c}')
            elif c.startswith('3') or c.startswith('0') or c.startswith('2'):
                symbol_list.append(f'sz{c}')
            else:
                symbol_list.append(f'sh{c}')
        url = f"https://qt.gtimg.cn/q={','.join(symbol_list)}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            for line in resp.text.strip().split(';'):
                line = line.strip()
                if not line or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                val = val.strip().strip('"')
                if not val or val == '':
                    continue
                parts = val.split('~')
                if len(parts) < 21:
                    continue
                raw_code = key.replace('v_', '').replace('sh', '').replace('sz', '').replace('bj', '')
                try:
                    quotes[raw_code] = {
                        'price': float(parts[3]) or 0,
                        'change_pct': float(parts[32]) if len(parts) > 32 else 0,
                        'volume': float(parts[6]) or 0,
                        'turnover': float(parts[37]) if len(parts) > 37 else 0,
                        'market_cap': float(parts[45]) if len(parts) > 45 else 0,
                    }
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"  [tencent] 批次 {i//BATCH+1} 失败: {e}")
        # 限流
        time.sleep(0.5)
    return quotes


def main():
    print("全A股行情刷新 (akshare主源 + 腾讯财经降级)")
    data = load()
    stocks = data.get('stocks', [])
    print(f"共 {len(stocks)} 只股票")

    all_q = None

    # 优先 akshare
    all_q = fetch_via_akshare()

    # 降级：腾讯财经
    if not all_q:
        print("  akshare 不可用, 降级使用腾讯财经...")
        codes = [s['code'] for s in stocks]
        all_q = fetch_via_tencent(codes)
        if all_q:
            print(f"  [tencent] 成功, {len(all_q)} 条")

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

    # 写 data.js
    today = datetime.now()
    if today.weekday() == 5: today = today.replace(day=today.day-1)
    elif today.weekday() == 6: today = today.replace(day=today.day-2)
    date_str = today.strftime('%Y-%m-%d')
    data['date'] = date_str
    if 'daily_summary' in data:
        data['daily_summary']['date'] = date_str
        data['daily_summary']['total_stocks'] = len(stocks)
        data['daily_summary']['up_count'] = sum(1 for s in stocks if s.get('change_pct', 0) > 0)
        data['daily_summary']['down_count'] = sum(1 for s in stocks if s.get('change_pct', 0) < 0)
        data['daily_summary']['flat_count'] = sum(1 for s in stocks if s.get('change_pct', 0) == 0)

    with open(DATA_JS_PATH, 'w', encoding='utf-8') as f:
        f.write(f"// 股票数据 - 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"window.__STOCK_DATA__ = {json.dumps(data, ensure_ascii=False)};\n")

    print(f"\n完成! 更新 {upd}/{len(stocks)} 只, 日期 {date_str}")


if __name__ == '__main__':
    main()
