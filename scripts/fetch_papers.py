#!/usr/bin/env python3
"""每日精选抓取：arXiv cs.RO 里机器人操作/学习相关的最新论文，择优 DAILY_PICK 篇。

只依赖 Python 标准库（无需 pip 安装任何东西）。
可选：设置环境变量 DEEPSEEK_API_KEY 后，会用 DeepSeek 给每篇生成中文"方法与贡献"
总结（模型 deepseek-flash）；未设置时回退到启发式抽取（摘要中的贡献句）。

用法:
    python scripts/fetch_papers.py            # 抓取并追加今天的精选
输出:
    data/papers.json                          # 网站数据源（保留最近 MAX_KEEP_DAYS 天）
"""
import json
import os
import re
import sys
import time
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.normpath(os.path.join(HERE, "..", "data", "papers.json"))

DAILY_PICK = 5
MAX_KEEP_DAYS = 45
PAGES = 2                 # 每页 100 条，共抓最新 200 条 cs.RO
PAGE_SLEEP = 3            # arXiv API 礼貌间隔（秒）
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# ---------------------------------------------------------------------------
# 5 条预设研究路线：关键词命中越多，相关度越高
# ---------------------------------------------------------------------------
ROUTES = {
    "affordance": {
        "name": "可寻址与接触几何",
        "keywords": ["affordance", "contact geometry", "grasp synthesis",
                     "contact point", "functional grasping", "hand-object interaction",
                     "contact-rich"],
    },
    "grasp": {
        "name": "抓取检测与位姿",
        "keywords": ["grasp detection", "grasp pose", "grasp planning", "antipodal",
                     "6-dof grasp", "grasp generation", "grasping", "gripper",
                     "grasp quality"],
    },
    "tactile": {
        "name": "触觉与闭环控制",
        "keywords": ["tactile", "touch sensing", "force sensing", "closed-loop grasping",
                     "gelsight", "slip detection", "sensorized"],
    },
    "learn": {
        "name": "操作学习与策略",
        "keywords": ["policy learning", "imitation learning", "reinforcement learning",
                     "vision-language-action", " vla ", "diffusion policy",
                     "behavior cloning", "manipulation policy", "foundation model",
                     "manipulation"],
    },
    "data": {
        "name": "数据·仿真·基准",
        "keywords": ["benchmark", "dataset", "sim-to-real", "sim2real",
                     "domain randomization", "simulation", "data scaling",
                     "teleoperation", "dexterous"],
    },
}

# 发表去向（arXiv comment 字段里常见）
VENUE_RE = re.compile(
    r"(CoRL|RSS|ICRA|IROS|NeurIPS|ICLR|ICML|CVPR|ICCV|ECCV|T-?RO\b|IJRR|RA-L|"
    r"Science Robotics|Nature Machine Intelligence|Nature\b)",
    re.I,
)

# 顶级机构（摘要里的 affiliation 命中）
TOP_ORGS = [
    "stanford", "uc berkeley", "berkeley", "carnegie mellon", "carnegie-mellon",
    "cmu", "mit", "massachusetts institute", "eth zurich", "eth z",
    "technical university of munich", "tu munich", "tsinghua", "peking university",
    "shanghai jiao tong", "hkust", "hong kong university of science",
    "chinese university of hong kong", "deepmind", "google deepmind",
    "physical intelligence", "openai", "nvidia", "toyota research",
    "max planck", "princeton", "georgia tech", "university of washington",
    "imperial college", "university of michigan", "kaist",
    "uc san diego", "ucsd", "ut austin", "tu darmstadt", "darmstadt",
    "national university of singapore", "bigai", "duke university",
]

# 顶级 PI 白名单（作者字段命中，权重最高）。易撞名的短 token 一律写全名防误报。
TOP_PIS = [
    # Berkeley BAIR
    "levine", "abbeel", "goldberg", "abhishek gupta", "lerrel pinto",
    # Stanford
    "chelsea finn", "shuran song", "fei-fei li", "li fei-fei", "jiajun wu",
    "c. karen liu", "karen liu", "dorsa sadigh", "marco pavone",
    "jeannette bohg", "karen bohg",
    # CMU
    "animesh garg", "david held", "deepak pathak", "oliver kroemer",
    "byron boots", "siddhartha srinivasa", "danfei xu",
    # MIT
    "russ tedrake", "pulkit agrawal", "daniela rus", "allison okamura",
    # 欧洲
    "danica kragic", "aula billard", "roland siegwart", "cecilia laschi",
    "roberto calandra", "jan peters", "georg martius", "oier mees",
    "edward johns", "stephen james",
    # 触觉/软体
    "wenzhen yuan",
    # 经典操作理论
    "oussama khatib", "matthew t. mason", "stefanie tellex",
    # 工业界前沿 lab PI 级
    "karol hausman", "brian ichter", "dieter fox", "yuke zhu",
    "sehoon ha", "yilun du", "boyuan chen", "jim fan", "danny driess",
    "andy zeng", "pete florence", "aravind rajeswaran", "nicolas heess",
    # 具身学习新生代
    "tony zhao", "tony z. zhao", "yanjie ze", "katerina fragkiadaki",
    "yunzhu li",
    # 中文圈
    "huazhe xu", "cewu lu", "song-chun zhu", "yixin zhu", "jia pan",
    "yun-hui liu", "max q.-h. meng", "michael y. wang", "xiaolong wang",
    "qiang li", "montgomery",
]

CONTRIB_RE = re.compile(
    r"(we propose|we introduce|we present|we develop|we design|we show|we demonstrate"
    r"|we achieve|we release|we contribute|state-of-the-art|outperform|first)",
    re.I,
)


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "manipdaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_latest_csro() -> list:
    """抓取 cs.RO 最新提交（atom feed）。"""
    base = "https://export.arxiv.org/api/query"
    entries = []
    for page in range(PAGES):
        qs = urllib.parse.urlencode({
            "search_query": "cat:cs.RO",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": page * 100,
            "max_results": 100,
        })
        url = f"{base}?{qs}"
        for attempt in range(3):
            try:
                xml_bytes = http_get(url)
                break
            except Exception as exc:  # 网络抖动重试
                print(f"[warn] fetch page {page} attempt {attempt + 1} failed: {exc}")
                time.sleep(5)
        else:
            continue
        root = ET.fromstring(xml_bytes)
        for entry in root.findall("a:entry", ATOM_NS):
            def txt(tag):
                node = entry.find(f"a:{tag}", ATOM_NS)
                return (node.text or "").strip() if node is not None else ""
            abs_url = txt("id")
            arxiv_id = abs_url.rstrip("/").split("/abs/")[-1]
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            authors = [a.find("a:name", ATOM_NS).text
                       for a in entry.findall("a:author", ATOM_NS)]
            comment_node = entry.find("arxiv:comment",
                                      {"arxiv": "http://arxiv.org/schemas/atom"})
            entries.append({
                "id": f"arxiv:{arxiv_id}",
                "title": re.sub(r"\s+", " ", txt("title")),
                "authors": authors,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "abstract": re.sub(r"\s+", " ", txt("summary")),
                "published": txt("published")[:10],
                "comment": (comment_node.text or "").strip() if comment_node is not None else "",
            })
        time.sleep(PAGE_SLEEP)
    return entries


def score_entry(e: dict) -> dict:
    """给单篇论文打相关度分并标注路线/机构。低于阈值返回 relevance=False。"""
    text = " " + (e["title"] + " " + e["abstract"] + " " + e["comment"]).lower() + " "
    route_hits = {}
    for key, cfg in ROUTES.items():
        hits = sum(1 for kw in cfg["keywords"] if kw in text)
        if hits > 0:
            route_hits[key] = hits
    title_lower = " " + e["title"].lower() + " "
    title_hits = sum(1 for cfg in ROUTES.values() for kw in cfg["keywords"]
                     if kw in title_lower)
    total = sum(route_hits.values())

    authors_lower = " " + ", ".join(e["authors"]).lower() + " "
    pis = [p for p in TOP_PIS if p in authors_lower]

    def word_hit(token: str) -> bool:
        # 词边界匹配，避免 "mit" 命中 "limitations" 这类误报
        return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text) is not None

    orgs = [o for o in TOP_ORGS if word_hit(o)]
    venue_m = VENUE_RE.search(e["comment"])

    # ---- 质量信号：区分 solid 工作与纯增量改进 ----
    pct_nums = re.findall(r"\d+(?:\.\d+)?\s*%", text)          # 量化实验结果
    solid_re = re.search(
        r"(benchmark|dataset|open.?sourc|hardware|platform|simulator"
        r"|real[- ]robot|new system)", text)

    score = 2.0 * total + title_hits + 3.0 * len(pis) + 1.5 * min(len(orgs), 2)
    if venue_m:
        score += 2.5
    score += 0.8 * min(len(pct_nums), 3)          # 有量化结果：solid 信号
    if solid_re:
        score += 1.0                              # 放出数据集/基准/硬件/开源
    if not pct_nums and not solid_re and not venue_m and not pis:
        score -= 1.2                              # 无数字无背书：疑似增量改进，降权

    relevant = total >= 2 or title_hits >= 1
    return {
        "score": round(score, 2),
        "routes": sorted(route_hits, key=route_hits.get, reverse=True),
        "route_hits": route_hits,
        "top_pis": pis,
        "orgs": orgs[:3],
        "venue": venue_m.group(0) if venue_m else "",
        "quant": bool(pct_nums),
        "solid": bool(solid_re),
        "relevant": relevant,
    }


def heuristic_contribution(abstract: str) -> str:
    """无 LLM 时：抽出摘要里带贡献信号的句子，拼成"方法与贡献"。"""
    sents = re.split(r"(?<=[.!?])\s+", abstract)
    picked = [s for s in sents if CONTRIB_RE.search(s)]
    return " ".join(picked[:3]) if picked else sents[0] if sents else ""


def deepseek_contribution(e: dict, api_key: str) -> str | None:
    """可选：DeepSeek 生成两句中文总结（方法 + 贡献）。失败返回 None。"""
    prompt = (
        "用一两句简体中文提炼这篇机器人论文最亮眼的部分："
        "第一句点出最核心、最新颖的想法（说清机制，不堆术语）；"
        "第二句给最亮眼的结果，有数字就带数字（成功率/提升幅度等）。"
        "不要空话套话，直接给干货：\n\n"
        f"标题: {e['title']}\n摘要: {e['abstract']}"
    )
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        # deepseek-flash 是推理模型，思考也要吃 token，上限放宽避免正文被截断
        "max_tokens": 800,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"[warn] deepseek summary failed for {e['id']}: {exc}")
        return None


def pick_today(entries: list, api_key: str | None) -> list:
    scored = []
    for e in entries:
        info = score_entry(e)
        if not info["relevant"]:
            continue
        e.update(info)
        scored.append(e)
    scored.sort(key=lambda x: -x["score"])
    picks = scored[:DAILY_PICK]
    for e in picks:
        summary = None
        if api_key:
            summary = deepseek_contribution(e, api_key)
        e["contribution"] = summary or heuristic_contribution(e["abstract"])
        e["summary_source"] = "deepseek" if summary else "heuristic"
    return picks


def load_existing() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"generated_at": "", "days": []}


def save(store: dict) -> None:
    store["generated_at"] = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY") or None
    print(f"[info] fetching latest cs.RO (llm={'on' if api_key else 'off'}) ...")
    entries = fetch_latest_csro()
    print(f"[info] got {len(entries)} entries, scoring ...")
    picks = pick_today(entries, api_key)
    today = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))
    ).strftime("%Y-%m-%d")

    store = load_existing()
    seen = {p["id"] for day in store["days"] for p in day["papers"]}
    new_picks = [p for p in picks if p["id"] not in seen]

    today_group = next((d for d in store["days"] if d["date"] == today), None)
    if today_group is None:
        today_group = {"date": today, "papers": []}
        store["days"].insert(0, today_group)
    if new_picks:
        today_group["papers"].extend(new_picks)

    # 只保留今天/最近 MAX_KEEP_DAYS 天，按日期倒序
    cutoff = (datetime.date.today() - datetime.timedelta(days=MAX_KEEP_DAYS)).isoformat()
    store["days"] = sorted((d for d in store["days"] if d["date"] >= cutoff),
                           key=lambda d: d["date"], reverse=True)

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    save(store)
    print(f"[done] {today}: picked {len(new_picks)} new papers")
    for p in new_picks:
        print(f"  - [{p['score']:>5}] {p['title'][:80]}")
    if picks and not new_picks:
        print("[info] today's picks were all duplicates; nothing added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
