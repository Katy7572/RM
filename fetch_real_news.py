"""
新闻舆情真实数据更新脚本
数据来源：AkShare (东方财富、财讯、央视)
用法：python fetch_real_news.py
输出：news_data.js（覆盖原有假数据）
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import re
import akshare as ak
from datetime import datetime
from typing import Dict, List

from pathlib import Path

# data.js / news_data.js 路径：优先脚本同级目录，不存在则用上一级（适配本地和 GitHub Actions）
_script_dir = Path(__file__).resolve().parent
DATA_JS_PATH = _script_dir / "data.js" if (_script_dir / "data.js").exists() else _script_dir.parent / "data.js"
NEWS_JS_PATH = _script_dir / "news_data.js" if (_script_dir / "news_data.js").exists() else _script_dir.parent / "news_data.js"


# ============================================================
# 配置区：需要跟踪的江苏上市公司代码列表（6位纯数字）
# 可从当前 data.js 中提取，也可以自己维护
# ============================================================
JIANGSU_CODES = [
    # 南京
    '601688', '600064', '601009', '601990', '600710', '600226',
    '600398', '600533', '300628',
    # 苏州
    '603259', '600105', '600200', '600527', '600667', '603501',
    '688008', '688012', '688036', '688088', '688111',
    # 无锡
    '600079', '600327', '600390', '300760', '002129',
    # 常州
    '300450', '600295', '300014', '300274', '600550',
    # 南通
    '600087', '600242', '600268', '002318',
    # 扬州/镇江/泰州/连云港/徐州/淮安/盐城/宿迁
    '600152', '600163', '600099', '600128', '600746',
    '600500', '600775', '600101', '600250', '600268',
    '600110', '600112', '600121', '600133', '600111',
    '600138', '600180', '600193', '600198', '600213',
    '600215', '600220',
    # 其他常见江苏股
    '002463', '600276', '605333', '603800', '601512',
    '601890', '603369', '603900', '002090', '002274',
    '601007', '600713', '600716', '600794', '600805',
    '600854', '603013', '603158', '603283', '603518',
    '603666', '603776', '603890', '603955', '603990',
    '605099', '605167', '605288', '605300', '300029',
    '300575', '300725', '300873', '300982', '301061',
    '688076', '688170', '688182', '688211', '688337',
    '688376', '688399', '688426', '688448', '688533',
]

# 每只股票最多拉几条新闻
NEWS_PER_STOCK = 5
# 财讯要闻拉几条
MAIN_NEWS_COUNT = 15
# 央视新闻拉几条
CCTV_NEWS_COUNT = 10


def fetch_stock_news(codes: List[str]) -> List[Dict]:
    """从东方财富拉取个股新闻"""
    news_list = []
    success_count = 0
    fail_count = 0

    for code in codes:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is None or df.empty:
                continue

            for _, row in df.head(NEWS_PER_STOCK).iterrows():
                title = str(row.get('新闻标题', '')).strip()
                if not title:
                    continue

                # 自动分类
                news_type = classify_news(title, str(row.get('新闻内容', '')))

                # 情感分析（简单关键词匹配）
                sentiment = analyze_sentiment(title)

                publish_time = str(row.get('发布时间', ''))
                # 统一时间格式
                if ' ' not in publish_time and 'T' in publish_time:
                    publish_time = publish_time.replace('T', ' ')

                news_list.append({
                    'stock_code': code,
                    'stock_name': str(row.get('关键词', '')),
                    'title': title,
                    'type': news_type,
                    'publish_time': publish_time,
                    'source': str(row.get('文章来源', '东方财富')),
                    'sentiment': sentiment,
                    'url': str(row.get('新闻链接', ''))
                })

            success_count += 1

        except Exception as e:
            fail_count += 1

    print(f'  个股新闻: 成功 {success_count} 只, 失败 {fail_count} 只, 共 {len(news_list)} 条')
    return news_list


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

            # 用摘要前50字作为标题
            title = summary[:50] + ('...' if len(summary) > 50 else '')

            news_list.append({
                'stock_code': '',
                'stock_name': '',
                'title': title,
                'type': '行业快讯',
                'publish_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'source': '财讯',
                'sentiment': 'neutral',
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


def classify_news(title: str, content: str) -> str:
    """根据标题和内容自动分类新闻"""
    text = title + content

    # 研报/调研类
    if any(kw in text for kw in ['调研', '机构调研', '研报', '评级', '目标价']):
        return '调研资讯'

    # 政策类（优先级高于公司公告，如"工信部出台XX政策"）
    if any(kw in text for kw in ['政策', '出台', '扶持', '补贴', '发改委', '国务院',
                                 '工信部', '央行', '证监会', '监管']):
        return '政策利好'

    # 默认：个股新闻即公司资讯
    return '公司资讯'


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


def load_existing_codes(filepath: str) -> List[str]:
    """从现有 data.js 提取股票代码列表"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'window\.__STOCK_DATA__\s*=\s*(\{.*\})\s*;', content, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            codes = [s['code'] for s in data.get('stocks', [])]
            print(f'  从 data.js 提取到 {len(codes)} 只股票代码')
            return codes
    except Exception as e:
        print(f'  读取 data.js 失败: {e}')
    return []


def main():
    print('=' * 50)
    print('新闻舆情真实数据更新')
    print('=' * 50)

    # 优先从 data.js 提取股票代码
    codes = load_existing_codes(str(DATA_JS_PATH))
    if not codes:
        print('  未提取到股票代码，使用默认列表')
        codes = JIANGSU_CODES
    else:
        # 合并默认列表，去重
        codes = list(set(codes + JIANGSU_CODES))

    print(f'  共 {len(codes)} 只股票需要跟踪\n')

    # 1. 拉取个股新闻
    print('[1/3] 拉取个股新闻...')
    stock_news = fetch_stock_news(codes)

    # 2. 拉取财讯要闻
    print('[2/3] 拉取财讯要闻...')
    main_news = fetch_main_financial_news()

    # 3. 拉取央视政策新闻
    print('[3/3] 拉取央视政策新闻...')
    policy_news = fetch_policy_news()

    # 合并所有新闻
    all_news = stock_news + main_news + policy_news

    # 按时间排序
    all_news.sort(key=lambda x: x.get('publish_time', ''), reverse=True)

    # 去重（基于标题）
    seen = set()
    unique_news = []
    for n in all_news:
        key = n['title'][:40]
        if key not in seen:
            seen.add(key)
            unique_news.append(n)

    print(f'\n合并去重后共 {len(unique_news)} 条新闻')

    # 统计类型分布
    from collections import Counter
    type_counts = Counter(n['type'] for n in unique_news)
    sentiment_counts = Counter(n['sentiment'] for n in unique_news)
    print(f'  类型分布: {dict(type_counts)}')
    print(f'  情感分布: {dict(sentiment_counts)}')

    # 写入 news_data.js
    output = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total': len(unique_news),
        'data': unique_news
    }

    js_content = f'// 新闻舆情真实数据 - 自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
    js_content += f'window.__NEWS_DATA__ = {json.dumps(output, ensure_ascii=False, indent=2)};\n'

    output_file = str(NEWS_JS_PATH)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(js_content)

    print(f'\n[OK] 已写入 {output_file}')
    print(f'   在 index-副本.html 的 <head> 中添加 <script src="news_data.js"></script> 即可使用')

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
            print('⚠️  未找到 window.__STOCK_DATA__，跳过 data.js 更新')
    except Exception as e:
        print(f'⚠️  更新 data.js 失败: {e}')


if __name__ == '__main__':
    main()
