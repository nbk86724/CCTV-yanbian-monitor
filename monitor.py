#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, os, json, logging
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

KEYWORDS = ["延边", "龙井", "延吉", "珲春", "敦化", "和龙", "汪清", "安图", "图们", "长白山"]

CHANNELS = [
    {"name": "朝闻天下", "channel": "CCTV-1/CCTV-13", "url": "https://tv.cctv.com/lm/zwtx/", "time": "06:00-08:30"},
    {"name": "新闻联播", "channel": "CCTV-1", "url": "https://tv.cctv.com/lm/xwlb", "time": "19:00"},
    {"name": "焦点访谈", "channel": "CCTV-13", "url": "https://tv.cctv.com/lm/jdft/", "time": "19:38"},
    {"name": "东方时空", "channel": "CCTV-13", "url": "https://tv.cctv.com/lm/dfsk/", "time": "20:00"},
    {"name": "晚间新闻", "channel": "CCTV-1", "url": "https://tv.cctv.com/lm/wjxw/", "time": "22:00"},
]

FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
DAYS_TO_CHECK = 2
SENT_IDS_FILE = "sent_ids.txt"
MAX_SENT_IDS = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def fetch_page(url, timeout=15):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"抓取失败 {url}: {e}")
        return ""

def extract_news_items(html, channel_name):
    items = []
    if not html:
        return items
    pattern = re.compile(r'<a[^>]+href="(https://tv\.cctv\.com/(\d{4})/(\d{2})/(\d{2})/[A-Za-z0-9]+\.shtml)"[^>]*>(.*?)</a>', re.DOTALL)
    for match in pattern.finditer(html):
        url = match.group(1)
        year, month, day = match.group(2), match.group(3), match.group(4)
        raw_title = match.group(5)
        title = re.sub(r'<[^>]+>', '', raw_title)
        title = title.replace('*完整版*', '').strip()
        title = re.sub(r'\s+', ' ', title)
        if not title or title in (channel_name, f"《{channel_name}》"):
            continue
        news_id = url.split("/")[-1].replace(".shtml", "")
        date_str = f"{year}-{month}-{day}"
        items.append({"id": news_id, "title": title, "url": url, "date": date_str})
    return items

def match_keywords(title):
    return [kw for kw in KEYWORDS if kw in title]

def load_sent_ids():
    sent = set()
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    sent.add(line)
    return sent

def save_sent_ids(sent_set):
    ids_list = list(sent_set)[-MAX_SENT_IDS:]
    with open(SENT_IDS_FILE, "w", encoding="utf-8") as f:
        for nid in ids_list:
            f.write(nid + "\n")

def send_feishu_message(news_list):
    if not FEISHU_WEBHOOK:
        logger.error("未配置FEISHU_WEBHOOK")
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content_lines = []
    content_lines.append([{"tag": "text", "text": f"发现时间：{now_str}"}])
    for i, item in enumerate(news_list, 1):
        if i > 1:
            content_lines.append([{"tag": "text", "text": "-------------------"}])
        content_lines.append([{"tag": "text", "text": f"频道：{item['channel']}"}])
        content_lines.append([{"tag": "text", "text": f"栏目：{item['channel_name']}（{item['time']}）"}])
        content_lines.append([{"tag": "text", "text": f"报道日期：{item['date']}"}])
        content_lines.append([{"tag": "text", "text": f"命中关键词：{'、'.join(item['keywords'])}"}])
        content_lines.append([{"tag": "text", "text": f"报道标题：{item['title']}"}])
        content_lines.append([{"tag": "a", "text": "点击查看视频", "href": item["url"]}])
    payload = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": f"📺 央视报道提醒（共{len(news_list)}条）", "content": content_lines}}}
    }
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(FEISHU_WEBHOOK, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info(f"飞书推送成功，共{len(news_list)}条")
                return True
            else:
                logger.error(f"飞书推送失败: {result}")
                return False
    except Exception as e:
        logger.error(f"飞书推送异常: {e}")
        return False

def main():
    logger.info("=" * 50)
    logger.info("央视延边报道监控开始运行")
    cutoff_date = (datetime.now() - timedelta(days=DAYS_TO_CHECK)).strftime("%Y-%m-%d")
    sent_ids = load_sent_ids()
    matched_news = []
    new_sent_ids = set()
    for ch in CHANNELS:
        logger.info(f"抓取: {ch['name']}")
        html = fetch_page(ch["url"])
        if not html:
            continue
        items = extract_news_items(html, ch["name"])
        for item in items:
            if item["date"] < cutoff_date:
                continue
            hits = match_keywords(item["title"])
            if not hits:
                continue
            if item["id"] in sent_ids:
                continue
            logger.info(f"★ 新匹配: [{item['date']}] {item['title']}")
            matched_news.append({
                "channel_name": ch["name"], "channel": ch["channel"],
                "time": ch["time"], "title": item["title"],
                "url": item["url"], "date": item["date"], "keywords": hits,
            })
            new_sent_ids.add(item["id"])
    if matched_news:
        success = send_feishu_message(matched_news)
        if success:
            sent_ids.update(new_sent_ids)
            save_sent_ids(sent_ids)
    else:
        logger.info("未发现新的延边相关报道")
    with open("last_run.txt", "w", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
    logger.info("监控运行结束")

if __name__ == "__main__":
    main()
