# -*- coding: utf-8 -*-
"""
机构业务动态看板 - 自动更新系统 v2
功能：
1. 每天抓取"今天+昨天"两天公告
2. 持久化存储最近7天数据
3. 生成JS文件供看板使用
4. 自动清理7天前数据

修复：巨潮API字段名已更新为 secCode/secName/announcementTitle/announcementTime(时间戳)
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests, json, pandas as pd, re, os, time
from datetime import datetime, timedelta
from pathlib import Path

# ===== 配置 =====
BASE_DIR = Path(__file__).parent
EXCEL_PATH = BASE_DIR.parent / "AH上市公司基本信息.xlsx"
OUTPUT_JS = BASE_DIR.parent / "capital_data.js"
OUTPUT_EXECUTIVE_JS = BASE_DIR.parent / "executive_data.js"
HISTORY_JSON = BASE_DIR / "capital_history.json"
EXEC_HISTORY_JSON = BASE_DIR / "executive_history.json"
HISTORY_DAYS = 7

CNINFO_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

SEARCH_CONFIG = [
    {"category": "股权激励/员工持股", "keywords": ["股权激励", "限制性股票", "股票期权", "员工持股"],
     "subTypes": {"股权激励": ["股权激励计划", "股权激励授予", "股权激励草案", "股权激励解除限售"],
                  "限制性股票": ["股权激励授予", "股权激励草案"],
                  "股票期权": ["股权激励授予", "股权激励草案"],
                  "员工持股": ["员工持股"]}},
    {"category": "增减持", "keywords": ["减持", "增持"],
     "subTypes": {"减持": ["减持计划", "减持结果", "减持进展", "大宗&竞价减持", "竞价减持"],
                  "增持": ["增持计划", "增持进展", "增持结果"]}},
    {"category": "股份回购", "keywords": ["股份回购", "回购股份"],
     "subTypes": {"股份回购": ["股份回购方案", "股份回购实施", "股份回购完成", "激励回购注销"]}},
    {"category": "委托理财", "keywords": ["委托理财", "闲置资金", "购买理财"],
     "subTypes": {"委托理财": ["委托理财"]}},
    {"category": "协议转让/控制权变更", "keywords": ["协议转让", "控制权变更", "股权转让", "公开征集"],
     "subTypes": {"协议转让": ["协议转让", "控制权变更", "公开征集受让方"]}}
]

EXECUTIVE_SEARCH_KEYWORDS = [
    # 综合关键词
    "高管变动", "董监高变动", "董事变更", "董事变动",
    "人事变动", "人员变动", "人事调整", "高管变更",
    # 离职/辞职类
    "高管离职", "总经理辞职", "副总经理辞职", "副总裁辞职",
    "财务总监辞职", "董事会秘书辞职", "董秘辞职", "监事辞职",
    "独立董事辞职", "独立董事离任", "董事辞职",
    "董事长辞职", "董事长辞任", "副董事长辞职",
    "辞任", "卸任", "不再担任",
    # 聘任/任命类
    "高管聘任", "聘任总经理", "聘任副总经理", "聘任总裁",
    "聘任副总裁", "聘任财务总监", "聘任董秘",
    "聘任董事会秘书", "新任董事", "新任总经理",
    # 补选/增补类
    "补选董事", "增补董事", "补选独立董事",
    # 换届类
    "董事会换届", "监事会换届", "换届选举",
    # 代行职责类
    "代行董事会秘书", "代行总经理", "代行职责",
    # 提名/候选人类
    "董事候选人", "监事候选人", "提名人选",
]

DIRECTION_MAP = {
    "股权激励/员工持股": "代发薪酬资产引入|员工行权融资|股东账户开立",
    "增减持": "增减持产品（算法交易、场外期权）|专项融资|市值管理",
    "增持": "专项融资|市值管理",
    "股份回购": "回购账户开立|回购融资|库存股再激励方案",
    "委托理财": "收益凭证定制|闲置资金资产配置|结构性存款引入",
    "协议转让/控制权变更": "并购财务顾问|控制权转让撮合|大宗减持税务筹划"
}

# ===== 公司信息加载 =====
def load_company_info():
    try:
        df = pd.read_excel(EXCEL_PATH)
        df.columns = ['code', 'name', 'industry', 'board', 'address']
        df['code'] = df['code'].fillna('').astype(str)
        df['name'] = df['name'].fillna('').astype(str)
        df['address'] = df['address'].fillna('').astype(str)
        def extract_city(address):
            if not address or address == 'nan': return "未知"
            for p in [r'([一-龥]+市)', r'([一-龥]+省)']:
                m = re.search(p, address)
                if m:
                    r = m.group(1)
                    if r in ['北京市','上海市','天津市','重庆市']: return r.replace('市','')
                    return r.replace('市','').replace('省','')
            return "未知"
        df['city'] = df['address'].apply(extract_city)
        company_map = {}
        for _, row in df.iterrows():
            code = str(row['code']).strip()
            if not code or code == 'nan': continue
            company_map[code] = {'name': row['name'], 'city': row['city'], 'industry': str(row['industry']) if pd.notna(row['industry']) else ''}
            base = code.split('.')[0]
            if base not in company_map: company_map[base] = company_map[code]
        print(f"已加载 {len(company_map)} 家公司信息")
        return company_map
    except Exception as e:
        print(f"加载公司信息失败: {e}")
        import traceback; traceback.print_exc()
        return {}

# ===== 巨潮API抓取 =====
def fetch_cninfo(keyword, date_start, date_end, page_size=30, max_pages=5):
    """分页+重试抓取巨潮公告，返回去重后的全量结果列表。"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': 'http://www.cninfo.com.cn',
        'Referer': 'http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=screen&searchKey='
    }
    all_results = []
    seen_ids = set()

    for page_num in range(1, max_pages + 1):
        params = {'pageNum': page_num, 'pageSize': page_size, 'tabName': 'fulltext',
                  'seDate': f"{date_start} ~ {date_end}", 'searchkey': keyword, 'isHLtitle': 'true'}
        # 重试最多3次
        for attempt in range(3):
            try:
                resp = requests.post(CNINFO_URL, data=params, headers=headers, timeout=30)
                data = resp.json()
                break
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"    请求失败(第{attempt+1}次重试，{wait}s后重试): {e}")
                    time.sleep(wait)
                else:
                    print(f"    请求失败(已重试3次): {e}")
                    return all_results if all_results else []
        else:
            return all_results if all_results else []

        anns = data.get('announcements', [])
        if not anns:
            break  # 无更多结果，终止分页

        # 去重（跨页可能重复）
        added = 0
        for ann in anns:
            aid = ann.get('announcementId')
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                all_results.append(ann)
                added += 1

        if added < len(anns):
            pass  # 有部分重复，继续下一页

        if len(anns) < page_size:
            break  # 最后一页

        time.sleep(0.3)  # 分页间限速

    return all_results

def ts_to_date(ts):
    """毫秒时间戳 -> YYYY-MM-DD"""
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d')
    return datetime.now().strftime('%Y-%m-%d')

def classify_announcement(title, keyword):
    for sub, keys in {
        "股权激励计划": ["股权激励计划", "股权激励草案"],
        "股权激励授予": ["授予"],
        "限制性股票": ["限制性股票"],
        "股票期权": ["股票期权"],
        "员工持股": ["员工持股"],
        "减持计划": ["减持计划", "拟减持", "预披露"],
        "减持结果": ["减持结果", "减持完成", "减持实施完毕"],
        "减持进展": ["减持进展", "减持实施"],
        "增持计划": ["增持计划"],
        "增持进展": ["增持进展", "增持实施", "首次增持"],
        "增持结果": ["增持结果", "增持完成"],
        "股份回购方案": ["回购方案", "回购预案", "拟回购"],
        "回购进展": ["回购进展", "回购实施"],
        "回购完成": ["回购完成", "回购实施完毕"],
        "委托理财": ["委托理财"],
        "协议转让": ["协议转让"],
        "控制权变更": ["控制权变更", "公开征集受让方"]
    }.items():
        if any(k in title for k in keys): return sub
    return keyword

def calculate_star(title, text, category, sub_type):
    import re
    def extract_amount(t):
        matches = re.findall(r'(\d+(?:\.\d+)?)\s*亿', t)
        amounts = [float(m) for m in matches if float(m) > 0]
        if not amounts:
            matches2 = re.findall(r'(\d+(?:\.\d+)?)\s*万', t)
            amounts = [float(m)/10000 for m in matches2 if float(m) > 0]
        return max(amounts) if amounts else 0
    title_text = title + ' ' + text
    if "控股" in title_text and "减持" in title_text:
        if any(k in title_text for k in ["计划","预披露","拟减持"]): return 4
        return 3
    if "5%" in title_text or "百分之五" in title_text:
        if any(k in title_text for k in ["计划","预披露"]): return 3
        return 2
    if "回购" in title_text:
        amt = extract_amount(title_text)
        if any(k in title_text for k in ["方案","预案","拟回购"]): return 4 if amt >= 1 else 3
        if any(k in title_text for k in ["完成","完毕"]): return 4
        if any(k in title_text for k in ["进展","实施"]): return 3
        return 2
    if "员工持股" in title_text: return 3 if any(k in title_text for k in ["草案","计划","办法"]) else 2
    if any(k in title_text for k in ["委托理财","闲置资金","自有资金"]):
        if any(k in title_text for k in ["额度","年度","使用自有"]):
            amt = extract_amount(title_text)
            return 4 if amt >= 10 else (3 if amt >= 1 else 3)
        return 2
    if any(k in title_text for k in ["授予","授予日","授予价格"]) and any(k in title_text for k in ["限制性股票","股票期权"]): return 3
    if any(k in title_text for k in ["减持计划","拟减持"]): return 3
    if any(k in title_text for k in ["减持结果","减持完成"]): return 3
    if "增持" in title_text and any(k in title_text for k in ["进展","实施"]): return 3
    return 2

def extract_summary(title, category, sub_type):
    title = re.sub(r'[　-〿＀-￯]', ' ', title).strip()
    if len(title) > 100:
        parts = title.split(':')
        if len(parts) >= 2: title = parts[1][:80]
        else: title = title[:80]
    return title

def parse_exec_change(title, summary):
    """解析高管变动类型 v3 - 先过滤噪音，再按优先级判断类型"""
    text = re.sub(r'<[^>]+>', '', title + ' ' + (summary or ''))
    
    # ===== 第一层：噪音过滤 =====
    # 债券受托管理报告（大量重复）
    if any(k in text for k in ['受托管理事务临时报告', '债权代理事务',
                                '临时受托管理', '债权代理人']):
        return None
    
    # 独立董事相关但非真正人事变动的
    if ('独立董事' in text or '独董' in text) and not any(k in text for k in [
        '独立董事辞职', '独立董事离任', '独立辞任', '独董辞职',
        '独立董事选举', '选任独立董事', '新任独立董事'
    ]):
        return None
    
    # 非人事公告（提名委员会和股东大会通知需要条件判断，避免误杀提名候选人和需要股东会审议的高管聘任）
    exec_context_kw = ['董事', '监事', '总经理', '副总经理', '总裁', '副总裁', '董秘', '财务总监', '高管', '候选人', '辞任', '聘任', '选举', '换届', '提名']
    if any(k in text for k in ['薪酬委员会', '审计委员会', '战略委员会',
                                '关联交易', '对外担保', '委托理财', '日常经营',
                                '年度报告', '季度报告', '半年度报告', '业绩预告',
                                '利润分配', '分红派息']):
        return None
    # 提名委员会 / 股东大会通知：仅当不含人事上下文时才过滤
    if any(k in text for k in ['提名委员会', '股东大会通知']):
        if not any(k in text for k in exec_context_kw):
            return None
    
    # ===== 第二层：判断变动类型（聘任优先于辞职） =====
    change_type = "变动"
    
    # 聘任类 - 最高优先级
    hire_keywords = [
        '聘任', '任命', '新任', '继任', '同意担任',
        '选举为', '当选为', '推举为'
    ]
    hire_contexts = [
        '总经理', '副总经理', '总裁', '副总裁', '经理', '副经理',
        '董事长', '副董事长', '董事', '监事', '监事长',
        '董秘', '董事会秘书', '财务总监', 'CFO', 'CEO', '首席'
    ]
    has_hire_kw = any(k in text for k in hire_keywords)
    has_hire_ctx = any(k in text for k in hire_contexts)
    if has_hire_kw and has_hire_ctx:
        change_type = "聘任"
    
    # 辞职类 - 仅当没有聘任上下文时
    if change_type == "变动":
        resign_patterns = [
            r'辞职', r'离任(?!.*选举)', r'辞去', r'辞任',
            r'免职', r'卸任', r'不再担任.{0,6}(职务|董事|监事|总|副总|经理|总裁|副总裁|总监|CFO|CEO|董秘)'
        ]
        if any(re.search(p, text) for p in resign_patterns):
            change_type = "辞职"
    
    # 换届类
    if change_type == "变动" and any(k in text for k in ['换届', '换届选举', '董事会换届', '监事会换届']):
        change_type = "换届"
    
    # ===== 第三层：提取信息 =====
    position = ""
    for kw in ["董事长","副董事长","董事","独立董事","监事","监事长",
                "总经理","副总经理","总裁","副总裁","CEO","CFO",
                "董秘","董事会秘书","财务总监","首席"]:
        if kw in text: position = kw; break
    
    person_match = re.search(r'([一-龥]{2,4})(先生|女士)', text)
    person_name = person_match.group(1) if person_match else ""
    reason = ""
    for kw in ["工作原因","个人原因","任期届满","年龄原因","退休","换届"]:
        if kw in text: reason = kw; break
    status = "已生效"
    if any(k in text for k in ["拟","将","待","审议","候选"]): status = "待生效"
    return {"change_type": change_type, "position": position, "person_name": person_name, "change_reason": reason, "status": status}

# ===== 历史数据管理 =====
def load_history(path):
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except: pass
    return {}

def save_history(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def clean_old_records(history, days):
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    for key in list(history.keys()):
        if key < cutoff: del history[key]

# ===== 主更新逻辑 =====
def run_update():
    today = datetime.now()
    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    date_today = today.strftime('%Y-%m-%d')
    
    # 周末检查（手动运行时可跳过）
    if False and today.weekday() == 5:
        print("今天是周六，跳过"); return
    if False and today.weekday() == 6:
        print("今天是周日，跳过"); return
    
    print(f"\n{'='*50}")
    print(f"开始更新 ({date_today} + {yesterday})")
    print(f"{'='*50}")
    
    company_map = load_company_info()
    
    # ===== 资本动作 =====
    print("\n[1/2] 抓取资本动作公告...")
    
    history = load_history(HISTORY_JSON)
    seen_keys = set()
    for date_key, records in history.items():
        for r in records:
            seen_keys.add(f"{r.get('code')}_{re.sub(r'<[^>]+>','',r.get('title',''))}")
    
    new_records = []
    
    for config in SEARCH_CONFIG:
        category = config['category']
        for keyword in config['keywords']:
            print(f"  抓取: {category} - {keyword}")
            anns = fetch_cninfo(keyword, yesterday, date_today)
            print(f"    返回 {len(anns)} 条原始结果")
            for ann in anns:
                # 使用新字段名
                title_clean = re.sub(r'<[^>]+>', '', ann.get('announcementTitle', ''))
                sec_code = ann.get('secCode', '') or ''
                id_key = f"{sec_code}_{title_clean}"
                if id_key in seen_keys: continue
                seen_keys.add(id_key)
                
                if any(kw in title_clean for kw in ['征集投票权','征集问题','网上说明会','征集投资者提问']): continue
                
                sub_type = classify_announcement(announcementTitle := ann.get('announcementTitle', ''), keyword)
                code = sec_code
                company_info = company_map.get(code, {})
                summary = extract_summary(announcementTitle, category, sub_type)
                star = calculate_star(announcementTitle, summary, category, sub_type)
                direction = DIRECTION_MAP.get(category, '')
                
                record = {
                    'id': ann.get('announcementId', ''),
                    'code': code,
                    'name': ann.get('secName', '') or company_info.get('name', ''),
                    'city': company_info.get('city', '未知'),
                    'mv': 0,
                    'category': category,
                    'subType': sub_type,
                    'summary': summary,
                    'date': ts_to_date(ann.get('announcementTime')),
                    'star': star,
                    'claimed': False,
                    'claimDept': '',
                    'direction': direction,
                    'url': ann.get('adjunctUrl', '')
                }
                # 补全PDF链接
                if record['url'] and not record['url'].startswith('http'):
                    record['url'] = 'https://static.cninfo.com.cn/' + record['url'].lstrip('/')
                new_records.append(record)
            time.sleep(0.5)
    
    print(f"  新增 {len(new_records)} 条资本动作")
    
    # 合并到历史
    for rec in new_records:
        date_key = rec['date']
        if date_key not in history: history[date_key] = []
        history[date_key].append(rec)
    
    clean_old_records(history, HISTORY_DAYS)
    save_history(HISTORY_JSON, history)
    
    all_data = []
    for date_key in sorted(history.keys(), reverse=True):
        all_data.extend(history[date_key])
    
    capital_js = f"// 资本动作数据 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    capital_js += f"window.__CAPITAL_DATA__ = {json.dumps(history, ensure_ascii=False, indent=2)};\n"
    Path(OUTPUT_JS).write_text(capital_js, encoding='utf-8')
    print(f"  资本动作JS已更新: {OUTPUT_JS} ({len(all_data)}条)")
    
    # ===== 高管变动 =====
    print("\n[2/2] 抓取高管变动公告...")
    
    exec_history = load_history(EXEC_HISTORY_JSON)
    exec_seen = set()
    for date_key, records in exec_history.items():
        for r in records:
            exec_seen.add(f"{r.get('stock_code')}_{re.sub(r'<[^>]+>','',r.get('title',''))}")
    
    exec_new = []
    
    for keyword in EXECUTIVE_SEARCH_KEYWORDS:
        print(f"  抓取: {keyword}")
        anns = fetch_cninfo(keyword, yesterday, date_today)
        print(f"    返回 {len(anns)} 条原始结果")
        if anns is None: continue
        for ann in anns:
            title_clean = re.sub(r'<[^>]+>', '', ann.get('announcementTitle', ''))
            sec_code = ann.get('secCode', '') or ''
            id_key = f"{sec_code}_{title_clean}"
            if id_key in exec_seen: continue
            exec_seen.add(id_key)
            
            if any(kw in title_clean for kw in ['征集投票权','征集问题','网上说明会','投资者关系']): continue
            
            parsed = parse_exec_change(ann.get('announcementTitle', ''), ann.get('announcementContent', ''))
            if parsed is None: continue  # 过滤噪音
            code = sec_code
            company_info = company_map.get(code, {})
            
            record = {
                'id': ann.get('announcementId', ''),
                'stock_code': code,
                'stock_name': ann.get('secName', '') or company_info.get('name', ''),
                'change_type': parsed['change_type'],
                'person_name': parsed['person_name'],
                'position': parsed['position'],
                'change_reason': parsed['change_reason'],
                'announce_date': ts_to_date(ann.get('announcementTime')),
                'status': parsed['status'],
                'title': title_clean,
                'url': ann.get('adjunctUrl', '')
            }
            # 补全PDF链接
            if record['url'] and not record['url'].startswith('http'):
                record['url'] = 'https://static.cninfo.com.cn/' + record['url'].lstrip('/')
            exec_new.append(record)
        time.sleep(0.5)
    
    print(f"  新增 {len(exec_new)} 条高管变动")
    
    for rec in exec_new:
        date_key = rec['announce_date']
        if date_key not in exec_history: exec_history[date_key] = []
        exec_history[date_key].append(rec)
    
    clean_old_records(exec_history, HISTORY_DAYS)
    save_history(EXEC_HISTORY_JSON, exec_history)
    
    exec_js = f"// 高管变动数据 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    exec_js += f"window.__EXECUTIVE_DATA__ = {json.dumps(exec_history, ensure_ascii=False, indent=2)};\n"
    Path(OUTPUT_EXECUTIVE_JS).write_text(exec_js, encoding='utf-8')
    
    all_exec = []
    for date_key in sorted(exec_history.keys(), reverse=True):
        all_exec.extend(exec_history[date_key])
    print(f"  高管变动JS已更新: {OUTPUT_EXECUTIVE_JS} ({len(all_exec)}条)")
    
    print(f"\n{'='*50}")
    print(f"更新完成!")
    print(f"资本动作: 累计 {len(all_data)} 条 (最近{HISTORY_DAYS}天)")
    print(f"高管变动: 累计 {len(all_exec)} 条 (最近{HISTORY_DAYS}天)")
    print(f"{'='*50}")

if __name__ == '__main__':
    run_update()
