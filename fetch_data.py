#!/usr/bin/env python3
"""
Fetches Pinho Law data from Google Sheets and injects it into index.html.
Reads: Feed (posts/reels/carrosseis) and Stories tabs.
Optional: Insights tab (Mês, Emoji, Título, Texto) overrides auto-generated insights.
"""

import os
import json
import re
from datetime import datetime
from calendar import monthrange

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    os.system("pip install gspread google-auth --quiet")
    import gspread
    from google.oauth2.service_account import Credentials

SHEET_ID = os.environ.get("SHEET_ID", "1Bcg8sB3SuI_au-hUElWrMP4qtJl8S0J6hFCcRu55qsg")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

PT_MONTHS = {1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
             7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}
PT_SHORT  = {1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
             7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"}


def parse_date(val):
    if not val or str(val).strip() == "":
        return None
    val = str(val).strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def parse_int(val):
    if val is None or str(val).strip() == "":
        return 0
    s = re.sub(r"[^\d]", "", str(val).strip())
    return int(s) if s else 0


def normalize_tipo(raw):
    raw = str(raw).strip()
    if "Reel" in raw:
        return "Reel"
    if "Carrossel" in raw or "Carousel" in raw:
        return "Carrossel"
    return "Imagem"


def rows_to_dicts(worksheet):
    rows = worksheet.get_all_values()
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded)))
    return result


def month_key(date_str):
    return date_str[:7] if date_str else None


def month_range_str(year, month):
    last = monthrange(year, month)[1]
    return f"01/{month:02d} — {last:02d}/{month:02d}/{year}"


def fmt_num(n):
    return f"{n:,}".replace(",", ".")


def auto_insights(mk, summary, posts):
    y, m = int(mk[:4]), int(mk[5:7])
    month_name = PT_MONTHS[m]
    total  = summary.get("total", 0)
    views  = summary.get("views", 0)
    avg    = views // total if total else 0
    reels  = summary.get("reels", 0)
    carros = summary.get("carrosseis", 0)
    imgs   = summary.get("imagens", 0)
    comps  = summary.get("compartilhamentos", 0)
    salvs  = summary.get("salvamentos", 0)
    curts  = summary.get("curtidas", 0)

    best = max(posts, key=lambda p: p["views"]) if posts else None
    dominant = "Reels" if reels >= carros and reels >= imgs else (
               "Carrosseis" if carros >= imgs else "Imagens")

    ins = []
    ins.append({
        "emoji": "📊",
        "title": f"{month_name} em números",
        "body": (f"{fmt_num(views)} visualizações em {total} posts — "
                 f"média de {fmt_num(avg)} views/post. "
                 f"Reels: {reels} | Carrosseis: {carros} | Imagens: {imgs}."),
    })
    if best:
        desc_short = best.get("desc", "")[:70].strip()
        ins.append({
            "emoji": "🏆",
            "title": f"Post mais visto: {best['tipo']}",
            "body": (f"{fmt_num(best['views'])} views e "
                     f"{best.get('compartilhamentos', 0)} compartilhamentos. "
                     f"\"{desc_short}...\""),
        })
    eng = curts + comps + salvs
    eng_rate = eng / views * 100 if views else 0
    ins.append({
        "emoji": "💬",
        "title": "Engajamento do mês",
        "body": (f"{fmt_num(curts)} curtidas, {comps} compartilhamentos, "
                 f"{salvs} salvamentos — taxa de {eng_rate:.1f}% sobre as visualizações."),
    })
    ins.append({
        "emoji": "🎯",
        "title": f"{dominant} lideram",
        "body": (f"Continue priorizando {dominant} para maximizar o alcance orgânico. "
                 f"{comps} compartilhamentos totais no mês."),
    })
    return ins


def main():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(creds_json)
            creds_file = f.name
    else:
        creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

    creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)

    # ── FEED ─────────────────────────────────────────────────────────────────
    ws_feed = sh.worksheet("Feed")
    raw_feed = rows_to_dicts(ws_feed)

    posts_by_month = {}
    for r in raw_feed:
        # Instagram export uses "Horário de publicação" for the date; fall back to "Data"
        date_val = r.get("Horário de publicação", "") or r.get("Data", "")
        date_str = parse_date(date_val)
        if not date_str:
            continue
        mk = month_key(date_str)
        if not mk:
            continue

        tipo = normalize_tipo(r.get("Tipo de post", ""))
        try:
            date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            date_display = date_str

        post = {
            "tipo": tipo,
            "date": date_display,
            "views": parse_int(r.get("Visualizações", 0)),
            "curtidas": parse_int(r.get("Curtidas", 0)),
            "comentarios": parse_int(r.get("Comentários", 0)),
            "compartilhamentos": parse_int(r.get("Compartilhamentos", 0)),
            "salvamentos": parse_int(r.get("Salvamentos", 0)),
            "alcance": parse_int(r.get("Alcance", 0)),
            "desc": str(r.get("Descrição", "")).strip(),
            "link": str(r.get("Link permanente", "")).strip(),
        }
        posts_by_month.setdefault(mk, []).append(post)

    for mk in posts_by_month:
        posts_by_month[mk].sort(key=lambda p: p["views"], reverse=True)

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    summary_by_month = {}
    for mk, posts in posts_by_month.items():
        summary_by_month[mk] = {
            "total": len(posts),
            "views": sum(p["views"] for p in posts),
            "curtidas": sum(p["curtidas"] for p in posts),
            "comentarios": sum(p["comentarios"] for p in posts),
            "salvamentos": sum(p["salvamentos"] for p in posts),
            "compartilhamentos": sum(p["compartilhamentos"] for p in posts),
            "alcance": sum(p["alcance"] for p in posts),
            "reels": sum(1 for p in posts if p["tipo"] == "Reel"),
            "carrosseis": sum(1 for p in posts if p["tipo"] == "Carrossel"),
            "imagens": sum(1 for p in posts if p["tipo"] == "Imagem"),
        }

    # ── STORIES ──────────────────────────────────────────────────────────────
    ws_stories = sh.worksheet("Stories")
    raw_stories = rows_to_dicts(ws_stories)

    stories_by_month = {}
    for r in raw_stories:
        date_val = r.get("Horário de publicação", "") or r.get("Data", "")
        date_str = parse_date(date_val)
        if not date_str:
            continue
        mk = month_key(date_str)
        if not mk:
            continue
        s = stories_by_month.setdefault(
            mk, {"total": 0, "views": 0, "reach": 0, "respostas": 0, "visitas": 0, "cliques": 0}
        )
        s["total"]     += 1
        s["views"]     += parse_int(r.get("Visualizações", 0))
        s["reach"]     += parse_int(r.get("Alcance", 0))
        s["respostas"] += parse_int(r.get("Respostas", 0))
        s["visitas"]   += parse_int(r.get("Visitas ao perfil", 0))
        s["cliques"]   += parse_int(r.get("Cliques no link", 0))

    # ── INSIGHTS ─────────────────────────────────────────────────────────────
    insights_by_month = {}
    try:
        ws_ins = sh.worksheet("Insights")
        for r in rows_to_dicts(ws_ins):
            mk = str(r.get("Mês", "")).strip()
            if not mk:
                continue
            insights_by_month.setdefault(mk, []).append({
                "emoji": str(r.get("Emoji", "📊")).strip(),
                "title": str(r.get("Título", "")).strip(),
                "body":  str(r.get("Texto", "")).strip(),
            })
        print(f"  Insights from sheet: {sum(len(v) for v in insights_by_month.values())} entries")
    except Exception:
        pass

    all_months = sorted(set(list(posts_by_month) + list(stories_by_month)))
    for mk in all_months:
        if mk not in insights_by_month:
            insights_by_month[mk] = auto_insights(
                mk, summary_by_month.get(mk, {}), posts_by_month.get(mk, [])
            )

    # ── AUXILIARY MAPS ────────────────────────────────────────────────────────
    months = sorted(all_months)
    labels, ranges, mnames, prev = {}, {}, {}, {}
    for i, mk in enumerate(months):
        y, m = int(mk[:4]), int(mk[5:7])
        labels[mk] = f"{PT_MONTHS[m]} {y}"
        ranges[mk] = month_range_str(y, m)
        mnames[mk] = PT_SHORT[m]
        prev[mk]   = months[i - 1] if i > 0 else None

    # ── INJECT INTO index.html ────────────────────────────────────────────────
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    J = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    data_block = (
        "// ── DATA ──\n"
        f"const POSTS={J(posts_by_month)};\n"
        f"const SUMMARY={J(summary_by_month)};\n"
        f"const STORIES={J(stories_by_month)};\n"
        f"const INSIGHTS={J(insights_by_month)};\n\n"
        f"const LABELS={J(labels)};\n"
        f"const RANGES={J(ranges)};\n"
        f"const PREV={J(prev)};\n"
        f"const MONTHS={J(months)};\n"
        f"const MNAMES={J(mnames)};"
    )

    html = re.sub(
        r"// ── DATA ──.*?(?=\s*\n\s*let curMonths=)",
        data_block,
        html,
        flags=re.DOTALL,
    )

    if months:
        html = re.sub(
            r'let curMonths=\["[^"]*"\];',
            f'let curMonths=["{months[-1]}"];',
            html,
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    total_posts = sum(len(v) for v in posts_by_month.values())
    print(f"✓ Injected {total_posts} posts across {len(months)} months.")
    print(f"  Stories months: {len(stories_by_month)} | Insights: {len(insights_by_month)}")
    print(f"  Latest month shown: {months[-1] if months else 'n/a'}")
    print(f"  Updated at: {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}")


if __name__ == "__main__":
    main()
