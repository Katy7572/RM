"""
L1 市场级新闻舆情更新脚本
数据来源：
  - 东方财富市场指数新闻（沪深300 / 中证500 / 上证50）
  - 东方财富关键词搜索（券商 / 调研 → 研报与调研资讯）
  - 央视新闻政策类新闻
用法：python fetch_real_news.py
输出：news_data.js（覆盖原有数据）
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import re
import signal
import platform
import akshare as ak
from datetime import datetime
from typing import Dict, List
from pathlib import Path

# 全局超时：5 分钟
GLOBAL_TIMEOUT = 5 * 60  # seconds

if platform.system() != 'Windows':
    def _timeout_handler(signum, frame):
        print(f'\n[!] 全局超时 ({GLOBAL_TIMEOUT}s)，强制退出。')
        sys.exit(1)
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(GLOBAL_TIMEOUT)
else:
    def _timeout_handler(signum, frame):
        pass

_script_dir = Path(__file__).resolve().parent
DATA_JS_PATH = _script_dir / "data.js" if (_script_dir / "data.js").exists() else _script_dir.parent / "data.js"
NEWS_JS_PATH = _script_dir / "news_data.js" if (_script_dir / "news_data.js").exists() else _script_dir.parent / "news_data.js"

# 市场代表性 ETF 代码
MARKET_CODES = ['510300', '510500', '510050']  # 沪深300 / 中证500 / 上证50
NEWS_PER_CODE = 5

# 调研/研报关键词（覆盖研报、券商动态、机构调研）
RESEARCH_KEYWORDS = ['券商', '调研', '研报']
NEWS_PER_KEYWORD = 5

# 央视新闻条数
CCTV_NEWS_COUNT = 10


def fetch_market_news() -> List[Dict]:
    """从东方财富拉取市场指数新闻"""
    news_list = []
    seen_titles = set()
    for code in MARKET_CODES:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is None or df.empty:
                continue
            for _, row in df.head(NEWS_PER_CODE).iterrows():
                title = str(row.get('新闻标题', '')).strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                content = str(row.get('新闻内容', ''))
                news_list.append({
                    'stock_code': '',
                    'stock_name': '',
                    'title': title[:60],
                    'type': '市场快讯',
                    'publish_time': str(row.get('发布时间', '')),
                    'source': '东方财富',
                    'sentiment': analyze_sentiment(title + content[:100]),
                    'url': str(row.get('新闻链接', ''))
                })
        except Exception as e:
            print(f'  {code} 市场新闻获取失败: {e}')
    # 去重
    seen = set()
    deduped = []
    for n in news_list:
        key = n['title'][:30]
        if key not in seen:
            seen.add(key)
            deduped.append(n)
    print(f'  市场新闻: {len(deduped)} 条')
    return deduped


def fetch_research_news() -> List[Dict]:
    """用关键词搜索拉取研报/调研资讯（替代逐个股票调用）"""
    news_list = []
    seen_titles = set()
    for kw in RESEARCH_KEYWORDS:
        try:
            df = ak.stock_news_em(symbol=kw)
            if df is None or df.empty:
                continue
            for _, row in df.head(NEWS_PER_KEYWORD).iterrows():
                title = str(row.get('新闻标题', '')).strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                content = str(row.get('新闻内容', ''))
                # 判断是研报还是调研
                is_survey = any(k in title for k in ['调研', '接待', '机构来访'])
                news_type = '调研信息' if is_survey else '研报资讯'
                news_list.append({
                    'stock_code': '',
                    'stock_name': '',
                    'title': title[:60],
                    'type': news_type,
                    'publish_time': str(row.get('发布时间', '')),
                    'source': '东方财富',
                    'sentiment': analyze_sentiment(title + content[:100]),
                    'url': str(row.get('新闻链接', ''))
                })
        except Exception as e:
            print(f'  "{kw}" 搜索失败: {e}')
    # 去重
    seen = set()
    deduped = []
    for n in news_list:
        key = n['title'][:30]
        if key not in seen:
            seen.add(key)
            deduped.append(n)
    print(f'  调研/研报资讯: {len(deduped)} 条')
    return deduped


def fetch_policy_news() -> List[Dict]:
    """从央视新闻拉取政策类新闻"""
    news_list = []
    try:
        df = ak.news_cctv()
        if df is None or df.empty:
            return news_list
        for _, row in df.head(CCTV_NEWS_COUNT).iterrows():
            title = str(row.get('title', '')).strip()
            if not title:
                continue
            content = str(row.get('content', ''))
            news_list.append({
                'stock_code': '',
                'stock_name': '',
                'title': title[:60],
                'type': '政策信息',
                'publish_time': str(row.get('date', '')),
                'source': '央视新闻',
                'sentiment': analyze_sentiment(title + content[:100]),
                'url': ''
            })
        print(f'  央视新闻: {len(news_list)} 条')
    except Exception as e:
        print(f'  央视新闻获取失败: {e}')
    return news_list


def analyze_sentiment(text: str) -> str:
    """简单情感分析"""
    positive_words = ['增长', '上涨', '利好', '突破', '创新高', '预增', '盈利',
                      '获', '中标', '签约', '突破', '领先', '优秀']
    negative_words = ['下跌', '下降', '亏损', '利空', '违规', '处罚', '风险',
                      '减持', '退市', '暴雷', '预警', '质疑', '纠纷', '诉讼']
    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)
    if pos_count > neg_count:
        return 'positive'
    elif neg_count > pos_count:
        return 'negative'
    return 'neutral'


def main():
    print('=' * 50)
    print('L1 市场级新闻舆情更新（市场指数 + 研报调研 + 央视）')
    print('=' * 50)

    print('[1/3] 拉取市场指数新闻（东方财富）...')
    market_news = fetch_market_news()

    print('[2/3] 拉取调研/研报资讯（关键词搜索）...')
    research_news = fetch_research_news()

    print('[3/3] 拉取央视政策新闻...')
    policy_news = fetch_policy_news()

    all_news = market_news + research_news + policy_news
    all_news.sort(key=lambda x: x.get('publish_time', ''), reverse=True)

    seen = set()
    unique_news = []
    for n in all_news:
        key = n['title'][:40]
        if key not in seen:
            seen.add(key)
            unique_news.append(n)

    print(f'\n合并去重后共 {len(unique_news)} 条新闻')

    output = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total': len(unique_news),
        'data': unique_news
    }

    js_content = f'// L1 市场级新闻舆情 - 自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
    js_content += f'window.__NEWS_DATA__ = {json.dumps(output, ensure_ascii=False, indent=2)};\n'

    output_file = str(NEWS_JS_PATH)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(js_content)
    print(f'\n[OK] 已写入 {output_file}')

    # 同时更新 data.js 中的 news 部分
    print('\n[可选] 更新 data.js 中的 news 数据...')
    try:
        with open(str(DATA_JS_PATH), 'r', encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'window\.__STOCK_DATA__\s*=\s*(\{.*\})\s*;', content, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            data['news'] = unique_news
            data['timestamp'] = datetime.now().isoformat()
            new_content = f'window.__STOCK_DATA__ = {json.dumps(data, ensure_ascii=False)};\n'
            with open(str(DATA_JS_PATH), 'w', encoding='utf-8') as f:
                f.write(new_content)
            print('[OK] 已更新 data.js 中的 news 部分')
        else:
            print('  未找到 window.__STOCK_DATA__，跳过 data.js 更新')
    except Exception as e:
        print(f'  更新 data.js 失败: {e}')


if __name__ == '__main__':
    main()
