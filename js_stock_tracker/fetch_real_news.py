"""
L1 市场级新闻舆情更新脚本
数据来源：AkShare (财讯要闻、央视新闻)
不再拉取个股新闻，避免全 A 股顺序调用导致的超时。
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

# 全局超时：5 分钟（仅 L1 两层 API，正常情况下 10 秒内完成）
GLOBAL_TIMEOUT = 5 * 60  # seconds

if platform.system() != 'Windows':
    def _timeout_handler(signum, frame):
        print(f'\n[!] 全局超时 ({GLOBAL_TIMEOUT}s)，强制退出。已获取的数据将保存。')
        sys.exit(1)
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(GLOBAL_TIMEOUT)
else:
    def _timeout_handler(signum, frame):
        pass  # Windows 不支持，跳过

_script_dir = Path(__file__).resolve().parent
DATA_JS_PATH = _script_dir / "data.js" if (_script_dir / "data.js").exists() else _script_dir.parent / "data.js"
NEWS_JS_PATH = _script_dir / "news_data.js" if (_script_dir / "news_data.js").exists() else _script_dir.parent / "news_data.js"

# 财讯要闻条数
MAIN_NEWS_COUNT = 15
# 央视新闻条数
CCTV_NEWS_COUNT = 10


def fetch_main_financial_news() -> List[Dict]:
    """从财讯要闻拉取市场动态"""
    news_list = []
    try:
        df = ak.stock_news_main_cx()
        if df is None or df.empty:
            return news_list

        for _, row in df.head(MAIN_NEWS_COUNT).iterrows():
            summary = str(row.get('summary', '')).strip()
            if not summary:
                continue

            tag = str(row.get('tag', ''))
            url = str(row.get('url', ''))
            title = summary[:50] + ('...' if len(summary) > 50 else '')

            news_list.append({
                'stock_code': '',
                'stock_name': '',
                'title': title,
                'type': '行业快讯',
                'publish_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'source': '财讯',
                'sentiment': analyze_sentiment(title),
                'url': url
            })

        print(f'  财讯要闻: {len(news_list)} 条')
    except Exception as e:
        print(f'  财讯要闻获取失败: {e}')

    return news_list


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
            sentiment = analyze_sentiment(title + content[:100])

            news_list.append({
                'stock_code': '',
                'stock_name': '',
                'title': title[:60],
                'type': '政策利好',
                'publish_time': str(row.get('date', '')),
                'source': '央视新闻',
                'sentiment': sentiment,
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
    print('L1 市场级新闻舆情更新（财讯 + 央视）')
    print('=' * 50)

    # 1. 拉取财讯要闻
    print('[1/2] 拉取财讯要闻...')
    main_news = fetch_main_financial_news()

    # 2. 拉取央视政策新闻
    print('[2/2] 拉取央视政策新闻...')
    policy_news = fetch_policy_news()

    # 合并所有新闻
    all_news = main_news + policy_news

    # 按时间排序
    all_news.sort(key=lambda x: x.get('publish_time', ''), reverse=True)

    # 去重（基于标题前 40 字）
    seen = set()
    unique_news = []
    for n in all_news:
        key = n['title'][:40]
        if key not in seen:
            seen.add(key)
            unique_news.append(n)

    print(f'\n合并去重后共 {len(unique_news)} 条新闻')

    # 写入 news_data.js
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
