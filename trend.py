"""GitHub AI skill/plugin 트렌드 보고서. 사용: python trend.py build | serve"""
import json, os, re, sys, html, threading, time, webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(DIR, "history.json")
REPORT = os.path.join(DIR, "report.html")
PORT = 8765
WEEKS = 7
# 토큰 없이도 동작(호출 제한만 빡빡함). 있으면 GITHUB_TOKEN 환경변수에 넣기
TOKEN = os.environ.get("GITHUB_TOKEN", "")
QUERIES = [
    "topic:claude-code", "topic:claude-skills", "topic:mcp-server", "topic:ai-agents",
    "topic:agent-skills", "topic:claude-code-plugin", '"claude code" in:name,description',
    '"claude plugin" in:name,description',
]
_lock = threading.Lock()


def api(path):
    req = Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "trend-report",
        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    with urlopen(req, timeout=30) as r:
        return json.load(r)


def collect():
    since = (datetime.now(timezone.utc) - timedelta(weeks=WEEKS)).strftime("%Y-%m-%d")
    repos, errors = {}, []
    for q in QUERIES:
        if not TOKEN:
            time.sleep(7)  # 비인증 검색은 분당 10회 제한
        try:
            data = api(f"/search/repositories?q={quote(q + f' pushed:>={since}')}&sort=stars&order=desc&per_page=50")
            for r in data["items"]:
                repos[r["full_name"]] = r
        except Exception as e:  # 호출 제한 등: 가진 데이터로 계속 진행
            errors.append(f"{q}: {e}")
    items = [{
        "name": r["full_name"], "url": r["html_url"], "desc": r["description"] or "",
        "stars": r["stargazers_count"], "forks": r["forks_count"], "watchers": 0,
        "created": r["created_at"], "lang": r["language"] or "", "topics": r.get("topics", []),
    } for r in repos.values()]
    # 조회수 대체 지표: 포크 + watcher(구독자). watcher는 포크 상위 20개만 조회
    wfile = os.path.join(DIR, "watchers.json")  # API 호출 제한(시간당 60회) 절약용 24시간 캐시
    try:
        with open(wfile, encoding="utf-8") as f:
            wc = json.load(f)
    except (OSError, ValueError):
        wc = {}
    for it in sorted(items, key=lambda x: -x["forks"])[:20]:
        ts, val = wc.get(it["name"], (0, 0))
        if time.time() - ts > 86400:
            try:
                val = api("/repos/" + it["name"])["subscribers_count"]
                wc[it["name"]] = (time.time(), val)
            except Exception:
                pass
        it["watchers"] = val
    with open(wfile, "w", encoding="utf-8") as f:
        json.dump(wc, f)
    return items, errors


def update_history(items):
    try:
        with open(HISTORY, encoding="utf-8") as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = {}
    now = datetime.now(timezone.utc)
    hist[now.isoformat()] = {i["name"]: i["stars"] for i in items}
    cutoff = now - timedelta(days=30)
    hist = {k: v for k, v in hist.items() if datetime.fromisoformat(k) > cutoff}
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f)
    return hist


def add_surge(items, hist):
    """최근 7일 별 증가량. 기준 스냅샷은 7일 전에 가장 가까운 것. 없으면 일평균 별로 근사."""
    now = datetime.now(timezone.utc)
    target = now - timedelta(days=7)
    older = [(abs((datetime.fromisoformat(k) - target).total_seconds()), v) for k, v in hist.items()
             if (now - datetime.fromisoformat(k)).total_seconds() > 3600]
    base = min(older, key=lambda x: x[0])[1] if older else {}
    for it in items:
        if it["name"] in base:
            it["surge"], it["surge_note"] = it["stars"] - base[it["name"]], "실측"
        else:
            age = max((now - datetime.fromisoformat(it["created"].replace("Z", "+00:00"))).days, 1)
            it["surge"], it["surge_note"] = round(it["stars"] / age * 7), "추정"


CACHE = os.path.join(DIR, "translations.json")


def ko(text):
    """설명을 한글로 번역(캐시 사용). shortcut: 비공식 구글 번역 엔드포인트, 막히면 원문 표시."""
    if not text:
        return text
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if text not in cache:
        try:
            url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ko&dt=t&q=" + quote(text)
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
                cache[text] = "".join(p[0] for p in json.load(r)[0])
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            return text
    return cache[text]


CSS = """
:root{--bg:#070912;--card:rgba(255,255,255,.045);--line:rgba(255,255,255,.09);--fg:#eef1ff;--mut:#8b93b5}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI','Malgun Gothic',system-ui,sans-serif;color:var(--fg);min-height:100vh;
background:radial-gradient(900px 500px at 8% -10%,#3b2a8f55,transparent),radial-gradient(800px 500px at 100% 0,#0e749055,transparent),
radial-gradient(700px 500px at 60% 110%,#be185d33,transparent),var(--bg)}
.wrap{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
header{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:16px;margin-bottom:24px}
h1{margin:0;font-size:clamp(26px,5vw,40px);letter-spacing:-.02em;background:linear-gradient(90deg,#a78bfa,#38bdf8 55%,#34d399);-webkit-background-clip:text;background-clip:text;color:transparent}
.ts{color:var(--mut);font-size:13px;margin-top:6px}
#b{border:0;color:#fff;font-size:15px;font-weight:600;padding:12px 20px;border-radius:12px;cursor:pointer;
background:linear-gradient(135deg,#7c3aed,#2563eb);box-shadow:0 0 24px #6d4aff66;transition:.2s}
#b:hover{transform:translateY(-1px);box-shadow:0 0 34px #6d4aff99}
#b:disabled{opacity:.45;cursor:default;box-shadow:none;transform:none}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:16px;backdrop-filter:blur(10px)}
.kpi{padding:16px 18px}
.kpi small{color:var(--mut);font-size:12px;letter-spacing:.04em}
.kpi b{display:block;font-size:30px;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.kpi span{font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
.card{padding:20px;margin-bottom:20px}
.card h2{margin:0 0 2px;font-size:20px}
.sub{color:var(--mut);font-size:13px;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:20px}
@media(max-width:560px){.grid{grid-template-columns:1fr}}
.row{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--line)}
.rk{flex:none;width:28px;height:28px;border-radius:9px;display:grid;place-items:center;font-size:13px;font-weight:700;background:#ffffff14;color:var(--mut)}
.r1{background:linear-gradient(135deg,#fde047,#f59e0b);color:#3b2a00}
.r2{background:linear-gradient(135deg,#e5e7eb,#9ca3af);color:#1f2937}
.r3{background:linear-gradient(135deg,#fdba74,#c2410c);color:#2b1204}
.main{flex:1;min-width:0}
.main a{color:var(--fg);font-weight:600;text-decoration:none;font-size:14.5px;word-break:break-all}
.main a:hover{color:var(--c)}
.d{color:var(--mut);font-size:12.5px;margin:2px 0 6px;line-height:1.45}
.bar{height:6px;background:#ffffff10;border-radius:9px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:9px;background:linear-gradient(90deg,var(--c),color-mix(in srgb,var(--c) 40%,#fff));box-shadow:0 0 12px var(--c)}
.val{flex:none;text-align:right;font-weight:700;font-size:15px;color:var(--c);font-variant-numeric:tabular-nums;min-width:74px}
.val small{display:block;color:var(--mut);font-weight:400;font-size:11px}
svg text{fill:var(--mut);font-size:11px}svg .lb{fill:var(--fg);font-size:11px}
.err{color:#fb7185;font-size:13px}
.tp{display:inline-block;vertical-align:1px;margin-left:4px;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:600;color:#c4b5fd;background:#a78bfa22;border:1px solid #a78bfa55;white-space:nowrap}
.pvb{margin-top:8px;background:#ffffff12;color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer;transition:.15s}
.pvb:hover{border-color:var(--c);color:var(--c);box-shadow:0 0 12px color-mix(in srgb,var(--c) 40%,transparent)}
dialog{width:min(820px,94vw);max-height:90vh;padding:0;border:1px solid var(--line);border-radius:20px;color:var(--fg);
background:linear-gradient(160deg,#171a33,#0c0e1d);box-shadow:0 20px 80px #000a}
dialog::backdrop{background:#02030acc;backdrop-filter:blur(4px)}
dialog .bd{padding:26px 24px 24px}dialog .x{position:sticky;top:10px;float:right;margin:10px 10px 0 0;border:0;background:#ffffff18;color:var(--fg);width:32px;height:32px;border-radius:50%;cursor:pointer;z-index:2}
dialog h3{margin:0 0 6px;font-size:21px}dialog h3 a{color:#a78bfa;text-decoration:none}
dialog h4{margin:20px 0 8px;font-size:14px;color:var(--mut);letter-spacing:.03em}
.pd{line-height:1.6;font-size:14px;margin:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:14px}
.tiles div{background:#ffffff0d;border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.tiles b{display:block;font-size:17px}.tiles small{color:var(--mut);font-size:11.5px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chips span{background:#a78bfa22;border:1px solid #a78bfa55;border-radius:99px;padding:4px 10px;font-size:12px}
.note{background:#fb718518;border:1px solid #fb718555;border-radius:12px;padding:10px 12px;margin-bottom:12px;font-size:13px;line-height:1.55;color:var(--fg)}
"""


def row_list(rows, key, fmt, sub):
    mx = max([key(r) for r in rows] + [1])
    out = ""
    for n, it in enumerate(rows, 1):
        out += (f"<div class='row'><span class='rk r{n}'>{n}</span><div class='main'>"
                f"<a href='{it['url']}' target='_blank'>{html.escape(it['name'])}</a> {badge(it)}"
                f"<div class='d'>{html.escape(ko(it['desc'][:200])[:130])}</div>"
                f"<div class='bar'><i style='width:{max(key(it), 0) / mx * 100:.1f}%'></i></div>"
                + (f"<button class='pvb' onclick=\"pv('{PV[it['name']]}')\">🔍 미리보기</button>" if n <= 3 and it["name"] in PV else "")
                + "</div>"
                f"<div class='val'>{fmt(it)}<small>{sub(it)}</small></div></div>")
    return out


def card(title, desc, color, body):
    return f"<div class='card' style='--c:{color}'><h2>{title}</h2><p class='sub'>{desc}</p>{body}</div>"


def bubble(items):
    """별(x) × 관심도(y) 로그 산점도. 원 크기=1주 급상승."""
    import math
    W, H, L, B, T, R = 1000, 380, 56, 40, 14, 20
    pts = items
    f = lambda v: math.log10(max(v, 0) + 1)
    xs, ys = [f(p["stars"]) for p in pts], [f(p["forks"] + p["watchers"]) for p in pts]
    x0, x1, y0, y1 = min(xs) - .1, max(xs) + .1, min(ys) - .1, max(ys) + .1
    px = lambda v: L + (f(v) - x0) / (x1 - x0) * (W - L - R)
    py = lambda v: H - B - (f(v) - y0) / (y1 - y0) * (H - B - T)
    smax = max([p["surge"] for p in pts] + [1])
    g = ""
    for t in (10, 100, 1000, 10000, 100000):
        if x0 < f(t) < x1:
            g += f"<line x1='{px(t):.0f}' x2='{px(t):.0f}' y1='{T}' y2='{H - B}' stroke='#ffffff14'/><text x='{px(t):.0f}' y='{H - B + 16}' text-anchor='middle'>{t:,}</text>"
        if y0 < f(t) < y1:
            g += f"<line y1='{py(t):.0f}' y2='{py(t):.0f}' x1='{L}' x2='{W - R}' stroke='#ffffff14'/><text x='{L - 6}' y='{py(t) + 4:.0f}' text-anchor='end'>{t:,}</text>"
    dots = ""
    for p in pts:
        r = 5 + 15 * (max(p["surge"], 0) / smax) ** .5
        c = "#34d399" if p["surge"] >= smax * .5 else "#a78bfa"
        dots += (f"<circle cx='{px(p['stars']):.0f}' cy='{py(p['forks'] + p['watchers']):.0f}' r='{r:.1f}' fill='{c}' fill-opacity='.35' stroke='{c}'>"
                 f"<title>{html.escape(p['name'])}\n별 {p['stars']:,} / 포크+watcher {p['forks'] + p['watchers']:,} / 급상승 +{p['surge']:,}</title></circle>")
    for p in sorted(pts, key=lambda p: -p["stars"])[:8]:
        dots += f"<text class='lb' x='{px(p['stars']) + 9:.0f}' y='{py(p['forks'] + p['watchers']) - 9:.0f}'>{html.escape(p['name'].split('/')[1][:18])}</text>"
    return (f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='별 대비 관심도 산점도'>{g}{dots}"
            f"<text x='{W / 2}' y='{H - 4}' text-anchor='middle'>별 수 (로그) →</text>"
            f"<text transform='translate(12 {H / 2}) rotate(-90)' text-anchor='middle'>포크+watcher (로그) →</text></svg>"
            "<p class='sub' style='margin:6px 0 0'>원 크기 = 1주 급상승 · <span style='color:#34d399'>●</span> 급상승 상위 / <span style='color:#a78bfa'>●</span> 그 외</p>")


DETAILS = os.path.join(DIR, "details.json")
PV = {}  # 저장소 이름 -> 미리보기 팝업 id (Top3만)
# 폴더·파일 이름으로 역할을 추정(저장소 내용을 분석한 것이 아니라 이름 기준 해석)
FOLDER = {
    "skills": ("🧩", "스킬 모음"), "SKILL.md": ("🧩", "스킬 정의"), "commands": ("⌨️", "슬래시 명령어"),
    "agents": ("🤖", "에이전트 정의"), "hooks": ("🪝", "자동 실행 훅"), ".claude-plugin": ("📦", "플러그인 설정"),
    "plugins": ("📦", "플러그인 모음"), "mcp": ("🔌", "MCP 서버"), "src": ("💻", "소스 코드"),
    "scripts": ("📜", "스크립트"), "docs": ("📚", "문서"), "examples": ("🧭", "예제"), "tests": ("🧪", "테스트"),
    "README.md": ("📖", "설명서"), "CLAUDE.md": ("🧠", "Claude 지침"), "package.json": ("📦", "Node 패키지"),
    "pyproject.toml": ("🐍", "Python 패키지"), "Dockerfile": ("🐳", "도커 설정"), ".github": ("⚙️", "GitHub 설정"),
}
PALETTE = ["#a78bfa", "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#f472b6", "#22d3ee", "#c084fc"]


def parse_readme(t):
    t = re.sub(r"```.*?```|<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    lines = [l.strip() for l in t.splitlines()]
    heads = [re.sub(r"[#*`]", "", l).strip(" -:") for l in lines if l.startswith("##")]
    heads = [h for h in heads if 2 < len(h) < 50][:6]
    paras = [l for l in lines if len(l) >= 40 and l[0] not in "#|->*[`!"]
    return " ".join(paras[:2])[:300], heads


def tree_jsdelivr(name):
    """jsDelivr 파일 목록에서 루트 항목을 뽑는다. GitHub API 한도와 무관. shortcut: 아주 큰 저장소는 jsDelivr가 거부해 API로 대체."""
    for ref in ("HEAD", "main", "master"):
        try:
            req = Request(f"https://data.jsdelivr.com/v1/packages/gh/{name}@{ref}?structure=flat", headers={"User-Agent": "trend-report"})
            with urlopen(req, timeout=30) as r:
                files = json.load(r)["files"]
        except Exception:
            continue
        top = {}
        for f in files:
            parts = f["name"].strip("/").split("/")
            top[parts[0]] = "dir" if len(parts) > 1 else top.get(parts[0], "file")
        if top:
            return [[n, t] for n, t in top.items()]
    return []


# 유형 분류: 이름 우선, 그다음 설명·토픽. 저장소 내용을 분석한 것이 아니라 키워드 기반 추정
TYPES = [("모음집", "📚", r"awesome|curated|collection"), ("MCP 서버", "🔌", r"\bmcp\b|mcp-server|model.context.protocol"),
         ("플러그인", "📦", r"plugin|marketplace"), ("스킬", "🧩", r"skill"), ("에이전트", "🤖", r"agent|harness")]


def kind(it):
    name = it["name"].split("/")[1].lower()
    text = " ".join([it["desc"], *it.get("topics", [])]).lower()
    for src in (name, text):
        for label, ic, pat in TYPES:
            if re.search(pat, src):
                return ic, label
    return "🛠️", "도구"


def badge(it):
    ic, label = kind(it)
    return f"<span class='tp'>{ic} {label}</span>"


def detail(name):
    """README 요약과 루트 폴더 구조. 24시간 캐시. 일부 실패해도 가진 만큼만 반환."""
    try:
        with open(DETAILS, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    d = cache.get(name)
    if d and time.time() - d["ts"] < 86400:
        return d
    d = {"ts": time.time(), "intro": "", "heads": [], "tree": []}
    try:
        with urlopen(Request(f"https://raw.githubusercontent.com/{name}/HEAD/README.md", headers={"User-Agent": "trend-report"}), timeout=20) as r:
            d["intro"], d["heads"] = parse_readme(r.read(40000).decode("utf-8", "replace"))
    except Exception:
        pass
    d["tree"] = tree_jsdelivr(name)  # 호출 제한이 없는 경로를 먼저 시도
    if not d["tree"]:
        try:
            d["tree"] = [[e["name"], e["type"]] for e in api(f"/repos/{name}/contents")]
        except Exception:
            pass
    if d["tree"]:  # 폴더 조회(API 제한 대상)가 실패하면 캐시하지 않고 다음에 재시도
        cache[name] = d
        with open(DETAILS, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    return d


def tree_svg(name, tree):
    cut = lambda s, n: s if len(s) <= n else s[:n - 1] + "…"
    ents = [(n, t) for n, t in tree if n in FOLDER or not n.startswith(".") and not n.upper().startswith("LICENSE")]
    ents.sort(key=lambda e: (e[0] not in FOLDER, e[1] != "dir"))
    ents = ents[:8]
    W = 720
    if not ents:
        return (f"<p class='sub'>폴더 구조를 가져오지 못했습니다. 아래 링크에서 직접 확인하세요.<br>"
                f"<a href='https://github.com/{name}' target='_blank' style='color:#a78bfa'>GitHub에서 폴더 구조 보기 ↗</a></p>")
    rows = (len(ents) + 3) // 4
    H = 118 + rows * 84
    out = (f"<rect x='200' y='10' width='320' height='46' rx='14' fill='#7c3aed33' stroke='#a78bfa'/>"
           f"<text class='lb' x='360' y='38' text-anchor='middle' style='font-size:14px;font-weight:700'>{html.escape(cut(name, 34))}</text>")
    for i, (n, t) in enumerate(ents):
        x, y, c = 16 + (i % 4) * 174, 100 + (i // 4) * 84, PALETTE[i % len(PALETTE)]
        ic, lab = FOLDER.get(n, ("📁", "폴더") if t == "dir" else ("📄", "파일"))
        out += (f"<path d='M360 56 C360 {y - 20}, {x + 78} {y - 30}, {x + 78} {y}' fill='none' stroke='{c}' stroke-opacity='.6' stroke-width='1.5'/>"
                f"<rect x='{x}' y='{y}' width='156' height='60' rx='12' fill='{c}' fill-opacity='.12' stroke='{c}'/>"
                f"<text class='lb' x='{x + 10}' y='{y + 25}' style='font-size:12.5px;font-weight:600'>{ic} {html.escape(cut(n, 16))}</text>"
                f"<text x='{x + 10}' y='{y + 45}'>{html.escape(lab)}</text>")
    return f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='{html.escape(name)} 폴더 구조 도식'>{out}</svg>"


def popup(it):
    try:
        d = detail(it["name"])
    except Exception:
        d = {"intro": "", "heads": [], "tree": []}
    tile = lambda big, lab: f"<div><b>{big}</b><small>{lab}</small></div>"
    tiles = (tile(f"⭐ {it['stars']:,}", "별") + tile(f"🍴 {it['forks']:,}", "포크")
             + tile(f"👀 {it['watchers']:,}", "watcher") + tile(f"🚀 +{it['surge']:,}", f"1주 증가({it['surge_note']})"))
    chips = "".join(f"<span>{html.escape(ko(h))}</span>" for h in d["heads"])
    return (f"<h3><a href='{it['url']}' target='_blank'>{html.escape(it['name'])}</a> {badge(it)}</h3>"
            f"<p class='pd'>{html.escape(ko(it['desc'][:200]))}</p><div class='tiles'>{tiles}</div>"
            f"<h4>📐 구조 도식</h4>{tree_svg(it['name'], d['tree'])}"
            f"<p class='sub'>저장소 루트의 폴더·파일을 이름 기준으로 해석한 것입니다. 실제 동작은 링크에서 확인하세요.</p>"
            f"<h4>📖 README 요약</h4><p class='pd'>{html.escape(ko(d['intro'])) or '(README를 불러오지 못했습니다)'}</p>"
            f"{'<h4>🧭 README 목차</h4><div class=chips>' + chips + '</div>' if chips else ''}")


def render(items, errors):
    top = lambda key: sorted(items, key=key, reverse=True)[:10]
    by_star, by_int, by_surge = top(lambda i: i["stars"]), top(lambda i: i["forks"] + i["watchers"]), top(lambda i: i["surge"])
    by_fork = top(lambda i: i["forks"])
    PV.clear()
    top3 = {i["name"]: i for lst in (by_star, by_surge, by_int, by_fork) for i in lst[:3]}
    PV.update({n: f"p{k}" for k, n in enumerate(top3)})
    previews = "".join(f"<div id='pv-{PV[n]}' hidden>{popup(i)}</div>" for n, i in top3.items())
    union = {i["name"]: i for i in by_star + by_int + by_surge}.values()
    kpi = lambda label, big, name: f"<div class='kpi'><small>{label}</small><b>{big}</b><span>{html.escape(name)}</span></div>"
    kpis = (kpi("수집된 저장소", f"{len(items):,}", f"최근 {WEEKS}주 내 활동 · 쿼리 {len(QUERIES)}개")
            + kpi("⭐ 최다 별", f"{by_star[0]['stars']:,}", by_star[0]["name"])
            + kpi("🚀 최고 급상승", f"+{by_surge[0]['surge']:,}", by_surge[0]["name"])
            + kpi("👀 최고 관심도", f"{by_int[0]['forks'] + by_int[0]['watchers']:,}", by_int[0]["name"]))
    cards = (
        card("⭐ 별 많이 받은 Top10", f"최근 {WEEKS}주 내 활동이 있는 AI skill·플러그인", "#fbbf24",
             row_list(by_star, lambda i: i["stars"], lambda i: f"{i['stars']:,}", lambda i: f"포크 {i['forks']:,}"))
        + card("🚀 1주일 급상승 Top10", "최근 7일 별 증가량 (기록 전 저장소는 '추정' = 일평균×7)", "#34d399",
               row_list(by_surge, lambda i: i["surge"], lambda i: f"+{i['surge']:,}", lambda i: f"{i['surge_note']} · 별 {i['stars']:,}")))
    cards2 = card("👀 관심도 Top10 (조회수 대체)", "GitHub는 타인 저장소 조회수를 공개하지 않아 포크+watcher 합계로 대체", "#38bdf8",
                  row_list(by_int, lambda i: i["forks"] + i["watchers"], lambda i: f"{i['forks'] + i['watchers']:,}",
                           lambda i: f"별 {i['stars']:,}"))
    note =("<div class='note'><b>🍴 포크(fork)란?</b> 다른 사람의 저장소를 <b>내 계정으로 통째로 복사</b>해 가는 것입니다. "
            "가져다 직접 쓰거나 고쳐 보려는 사람이 하는 행동이라, 포크가 많다 = <b>실제로 쓰이는 프로젝트</b>라는 뜻입니다. "
            "별(⭐)이 '좋아 보인다'는 북마크라면 포크는 한 걸음 더 나간 관심입니다.</div>")
    cards3 = card("🍴 포크 많이 된 Top10", "복사해 가서 실제로 써 보거나 고쳐 보는 사람이 많은 순", "#fb7185",
                  note + row_list(by_fork, lambda i: i["forks"], lambda i: f"{i['forks']:,}", lambda i: f"별 {i['stars']:,}"))
    err = f"<p class='err'>일부 수집 실패(호출 제한 가능): {html.escape('; '.join(errors))}</p>" if errors else ""
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI 트렌드 보고서</title><style>{CSS}</style></head><body><div class="wrap">
<header><div><h1>AI 트렌드 보고서</h1><div class="ts">GitHub skill·플러그인 · 수집 시각 {now}<br>유형 배지(📦 플러그인 · 🧩 스킬 · 🔌 MCP 서버 · 🤖 에이전트 · 📚 모음집 · 🛠️ 도구)는 이름·설명·토픽 키워드로 자동 추정한 값입니다</div></div>
<button id="b" onclick="go()">🔄 실시간 수집</button></header>{err}
<div class="kpis">{kpis}</div>
{card("📊 별 × 관심도 지도", "오른쪽 위일수록 인기와 활용도가 모두 높은 프로젝트 (원에 마우스를 올려 보세요)", "#a78bfa", bubble(list(union)))}
<div class="grid">{cards}{cards2}{cards3}</div>
</div>{previews}
<dialog id="dlg"><button class="x" onclick="dlg.close()" aria-label="닫기">✕</button><div class="bd"></div></dialog>
<script>
const dlg = document.getElementById('dlg');
function pv(id){{dlg.querySelector('.bd').innerHTML=document.getElementById('pv-'+id).innerHTML;dlg.showModal();dlg.scrollTop=0}}
dlg.addEventListener('click',e=>{{if(e.target===dlg)dlg.close()}});
const live = ['localhost','127.0.0.1'].includes(location.hostname), b = document.getElementById('b');
if(!live){{b.textContent='🔄 새로고침';b.onclick=()=>location.replace(location.pathname+'?t='+Date.now());
 setInterval(()=>b.onclick(),600000)}}  // 클라우드 화면: 서버가 없으니 10분마다 최신 배포본을 다시 불러옴
async function go(){{b.disabled=true;b.textContent='수집 중… (최대 1분)';
 try{{await fetch('/refresh',{{method:'POST'}});location.reload()}}catch(e){{b.textContent='실패 - 다시 시도';b.disabled=false}}}}
</script></body></html>"""



KST = timezone(timedelta(hours=9))


def workflow_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "")  # GitHub Actions에서만 설정됨
    return f"https://github.com/{repo}/actions/workflows/daily.yml" if repo else ""


def render_mail(items, errors):
    """메일용 HTML. 메일 프로그램은 JS·팝업·CSS 변수를 막으므로 표와 인라인 스타일만 쓴다."""
    top = lambda key: sorted(items, key=key, reverse=True)[:10]
    sections = [("⭐ 별 많이 받은 Top10", top(lambda i: i["stars"]), lambda i: f"⭐ {i['stars']:,}"),
                ("🚀 1주일 급상승 Top10", top(lambda i: i["surge"]), lambda i: f"+{i['surge']:,} ({i['surge_note']})"),
                ("👀 관심도 Top10 (포크+watcher)", top(lambda i: i["forks"] + i["watchers"]), lambda i: f"{i['forks'] + i['watchers']:,}"),
                ("🍴 포크 많이 된 Top10", top(lambda i: i["forks"]), lambda i: f"🍴 {i['forks']:,}")]
    td = "padding:7px 6px;border-bottom:1px solid #e5e7eb;vertical-align:top"
    body = ""
    for title, rows, fmt in sections:
        trs = "".join(
            f"<tr><td style='{td};color:#6b7280;width:22px'>{n}</td><td style='{td}'>"
            f"<a href='{it['url']}' style='color:#4f46e5;font-weight:600;text-decoration:none'>{html.escape(it['name'])}</a> "
            f"<span style='font-size:11px;color:#6d28d9'>{' '.join(kind(it))}</span>"
            f"<div style='color:#6b7280;font-size:12px;margin-top:2px'>{html.escape(ko(it['desc'][:200])[:110])}</div></td>"
            f"<td style='{td};text-align:right;white-space:nowrap;font-weight:700'>{fmt(it)}</td></tr>" for n, it in enumerate(rows, 1))
        body += f"<h3 style='margin:22px 0 4px;font-size:16px;color:#111827'>{title}</h3><table width='100%' cellspacing='0' style='font-size:13px'>{trs}</table>"
    pages = os.environ.get("REPORT_URL", "")
    run = workflow_url()
    btns = "".join(f"<a href='{u}' style='display:inline-block;margin:0 6px 6px 0;padding:10px 16px;border-radius:8px;background:{c};color:#fff;font-weight:600;text-decoration:none;font-size:14px'>{t}</a>"
                   for u, t, c in ((pages, "📊 전체 보고서 보기", "#4f46e5"), (run, "🔄 지금 새로 수집", "#0f766e")) if u)
    err = f"<p style='color:#dc2626;font-size:12px'>일부 수집 실패: {html.escape('; '.join(errors))}</p>" if errors else ""
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return (f"<div style='max-width:640px;margin:0 auto;font-family:Segoe UI,Malgun Gothic,sans-serif;color:#111827'>"
            f"<h2 style='margin:0'>AI 트렌드 보고서</h2><div style='color:#6b7280;font-size:12px;margin:2px 0 14px'>{now} (KST) 기준 · 최근 {WEEKS}주 활동 저장소 {len(items):,}개 분석</div>"
            f"{btns}{err}{body}<p style='color:#9ca3af;font-size:11px;margin-top:24px'>유형 배지는 이름·설명·토픽으로 자동 추정한 값이며, "
            f"조회수는 GitHub가 공개하지 않아 포크+watcher로 대체했습니다.</p></div>")


def send_mail(subject, body):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    user, pw, to = os.environ["SMTP_USER"], os.environ["SMTP_PASS"], os.environ["MAIL_TO"]
    # 값이 비어 있으면(GitHub Secret 미등록) 네이버 기본값 사용. 네이버는 로그인에 아이디만, 보내는 주소는 전체 주소여야 함
    host = os.environ.get("SMTP_HOST") or "smtp.naver.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    sender = os.environ.get("MAIL_FROM") or (user if "@" in user else user + "@naver.com")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.attach(MIMEText("HTML을 지원하는 메일 프로그램에서 확인하세요.", "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL(host, port, timeout=60) as s:
        s.login(user.split("@")[0] if "naver" in host else user, pw)
        s.send_message(msg)


def build():
    with _lock:
        items, errors = collect()
        if not items:
            raise SystemExit("수집 결과 없음: " + "; ".join(errors))
        add_surge(items, update_history(items))
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write(render(items, errors))
    print("saved", REPORT)
    return items, errors


def render_telegram(items):
    """텔레그램용 요약(4096자 제한): 항목별 Top5, 이름·유형·수치만."""
    top = lambda key: sorted(items, key=key, reverse=True)[:5]
    sections = [("⭐ 별", top(lambda i: i["stars"]), lambda i: f"{i['stars']:,}"),
                ("🚀 급상승", top(lambda i: i["surge"]), lambda i: f"+{i['surge']:,}"),
                ("👀 관심도", top(lambda i: i["forks"] + i["watchers"]), lambda i: f"{i['forks'] + i['watchers']:,}"),
                ("🍴 포크", top(lambda i: i["forks"]), lambda i: f"{i['forks']:,}")]
    out = f"<b>AI 트렌드 보고서</b> · {datetime.now(KST):%m/%d %H:%M}\n"
    for title, rows, fmt in sections:
        out += f"\n<b>{title} Top5</b>\n"
        out += "".join(f"{n}. <a href='{i['url']}'>{html.escape(i['name'])}</a> {kind(i)[0]} {fmt(i)}\n" for n, i in enumerate(rows, 1))
    return out


def send_telegram(text):
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    buttons = [[{"text": t, "url": u}] for t, u in (("📊 전체 보고서 보기", os.environ.get("REPORT_URL", "")),
                                                   ("🔄 지금 새로 수집", workflow_url())) if u]
    body = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": buttons}}
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            r.read()
    except HTTPError as e:  # 텔레그램이 알려주는 사유(예: chat not found, Unauthorized)를 보여준다
        raise RuntimeError(f"{e.code} {json.load(e).get('description', '')}") from None


def check():
    """등록된 Secrets 점검. 값은 절대 출력하지 않고 등록 여부·형식·실제 로그인/조회 결과만 보여준다."""
    import builtins, smtplib

    def print(m):  # 오류 표시(annotation)로 내보내면 로그인 없이도 실행 결과 화면과 API에서 읽을 수 있다
        builtins.print(f"::{'notice' if m.startswith('✅') else 'warning'}::{m}")
    env = lambda k: os.environ.get(k, "")
    rules = {"SMTP_USER": lambda v: bool(v), "SMTP_PASS": lambda v: bool(v),
             "MAIL_TO": lambda v: "@" in v, "TELEGRAM_BOT_TOKEN": lambda v: bool(re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", v)),
             "TELEGRAM_CHAT_ID": lambda v: bool(re.fullmatch(r"-?\d+", v))}
    hint = {"SMTP_USER": "네이버 아이디", "SMTP_PASS": "애플리케이션 비밀번호", "MAIL_TO": "이메일 주소(@ 포함)",
            "TELEGRAM_BOT_TOKEN": "123456789:ABC... 형태", "TELEGRAM_CHAT_ID": "숫자만(예: 123456789)"}
    for k, ok in rules.items():
        v = env(k)
        if not v:
            print(f"❌ {k}: 등록되지 않았거나 비어 있음")
        elif v != v.strip():
            print(f"⚠️ {k}: 앞뒤에 공백/줄바꿈이 들어 있음 → 다시 등록하세요")
        elif not ok(v):
            print(f"⚠️ {k}: 형식이 이상함 ({hint[k]})")
        else:
            print(f"✅ {k}: 등록됨, 형식 정상")
    if env("SMTP_USER") and env("SMTP_PASS"):
        host = env("SMTP_HOST") or "smtp.naver.com"
        try:
            with smtplib.SMTP_SSL(host, int(env("SMTP_PORT") or 465), timeout=30) as s:
                s.login(env("SMTP_USER").split("@")[0] if "naver" in host else env("SMTP_USER"), env("SMTP_PASS"))
            print(f"✅ 메일 서버({host}) 로그인 성공")
        except Exception as e:
            print(f"❌ 메일 서버 로그인 실패: {type(e).__name__} → 아이디·애플리케이션 비밀번호·SMTP 사용 설정 확인")
    if env("TELEGRAM_BOT_TOKEN"):
        def tg(method, **q):
            url = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/{method}?" + "&".join(f"{a}={quote(str(b))}" for a, b in q.items())
            with urlopen(url, timeout=30) as r:
                return json.load(r)["result"]
        try:
            print(f"✅ 텔레그램 봇 확인됨: @{tg('getMe')['username']}")
        except Exception as e:
            print(f"❌ 텔레그램 토큰이 올바르지 않음: {type(e).__name__}")
        else:
            if env("TELEGRAM_CHAT_ID"):
                try:
                    tg("getChat", chat_id=env("TELEGRAM_CHAT_ID"))
                    print("✅ 텔레그램 채팅 ID 확인됨")
                except Exception as e:
                    print(f"❌ 채팅 ID 확인 실패({type(e).__name__}) → 숫자 ID가 맞는지, 봇에게 먼저 Start를 눌렀는지 확인")


def ci():
    """GitHub Actions용: 수집, Pages용 사본 저장, 메일·텔레그램 발송. 설정된 채널만 보내고 하나가 실패해도 나머지는 시도."""
    import shutil
    items, errors = build()
    os.makedirs("_site", exist_ok=True)
    shutil.copy(REPORT, os.path.join("_site", "index.html"))
    channels = []
    if os.environ.get("SKIP_SEND") == "true":  # 시험 실행(push 트리거): 수집·보고서·게시만 하고 발송은 하지 않음
        print("::notice::시험 실행이라 메일·텔레그램 발송은 건너뜀")
        return
    if os.environ.get("SMTP_USER"):
        channels.append(("메일", lambda: send_mail(f"[AI 트렌드 보고서] {datetime.now(KST):%m/%d} 오늘의 Top10", render_mail(items, errors))))
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        channels.append(("텔레그램", lambda: send_telegram(render_telegram(items))))
    failed = []
    for name, fn in channels:
        try:
            fn()
            print(name, "발송 완료")
            print(f"::notice::{name} 발송 완료")
        except Exception as e:  # 오류 사유를 보여주되 비밀값은 가린다
            failed.append(name)
            why = f"{type(e).__name__}: {e}"
            for k in ("TELEGRAM_BOT_TOKEN", "SMTP_PASS", "SMTP_USER"):
                if os.environ.get(k):
                    why = why.replace(os.environ[k], "***")
            print(f"::warning::{name} 발송 실패 - {why[:300]}")
    if not channels:
        print("::warning::발송 채널이 설정되지 않았습니다 (SMTP_USER 또는 TELEGRAM_BOT_TOKEN 필요)")
    if channels and len(failed) == len(channels):
        raise SystemExit("모든 발송 채널 실패")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # pythonw는 stderr가 없어서 기본 로그 출력이 연결을 끊는다
        pass

    def do_GET(self):
        with open(REPORT, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            build()
            self.send_response(200)
        except BaseException:  # SystemExit 포함
            self.send_response(500)
        self.end_headers()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "build":
        build()
    elif cmd == "ci":
        ci()
    elif cmd == "check":
        check()
    else:
        if cmd == "morning" or not os.path.exists(REPORT):  # morning: 매일 아침 새로 만든 뒤 브라우저로 보여줌
            build()
        url = f"http://localhost:{PORT}"
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        except OSError:  # 이미 서버가 떠 있으면 새로 만든 보고서를 그 서버로 보여주면 된다
            webbrowser.open(url)
            sys.exit()
        webbrowser.open(url)
        srv.serve_forever()
