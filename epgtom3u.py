import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import io

# ==========================================================
# 1. KONFIGURASI SUMBER (M3U & EPG)
# ==========================================================

EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"                   
]

MASTER_SOURCES = [
    "https://raw.githubusercontent.com/mimipipi22/lalajo/refs/heads/main/playlist25", # (1)
    "https://semar25.short.gy",                                                       # (2)
    "https://deccotech.online/tv/tvstream.html",                                      # (3)
    "https://bit.ly/KPL203",                                                          # (4)
    "https://freeiptv2026.tsender57.workers.dev",                                     # (5)
    "https://liveevent.iptvbonekoe.workers.dev",                                      # (6)
    "http://sauridigital.my.id/kerbaunakal/2026TVGNS.html",                           # (7)
    "https://bit.ly/TVKITKAT",                                                        # (8)
    "https://spoo.me/tvplurl04",                                                     # (9)
    "https://aspaltvpasti.top/xxx/merah.php"                                          # (10)
]

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 
M3U_HEADER = '#EXTM3U url-tvg="https://www.open-epg.com/generate/bXxbrwUThe.xml" name="🔴 BAKUL WIFI TV PREMIUM"'

# ==========================================================
# 2. MESIN SENSOR ANTI-SAMPAH (VERSI FINAL V2)
# ==========================================================

def normalisasi(n):
    n = n.lower().strip()
    n = re.sub(r'\b(?:champions?\s*tv|ctv)\s*(\d+)\b', r'champions tv \1', n)
    return re.sub(r'\bsports?\s+stars?\b', 'sportstars', re.sub(r'\bspo\s+tv\b', 'spotv', n))

def is_allowed_content(title, ch_name):
    if not title: return False
    t, c = title.lower(), ch_name.lower()

    # --- A. GLOBAL CHANNEL FILTER (Pembersih Saluran Non-Sport) ---
    channel_haram = [
        'awani', 'ria', 'oasis', 'prima', 'rania', 'citra', 'hijrah', 'ceria', 'warna', 
        'shiq', 'kulliyyah', 'vellithirai', 'vinmeen', 'mekkah', 'quran', 'religi', 
        'news', 'berita', 'cgtn', 'arirang', 'cctv', 'tvri', 'makkah', 'al jazeera', 'cnn'
    ]
    if any(x in c for x in channel_haram): return False

    # --- B. DAFTAR HARAM (Anti-Highlight & Siaran Tunda) ---
    haram_keywords = [
        "delay", "replay", "re-run", "siaran ulang", "recorded", "archives", "tunda", 
        "tayangan ulang", "rekap", "ulangan", "rakaman", "cuplikan", "sorotan", "best of", 
        "planet", "news", "studio", "update", "talk", "show", "weekly", "kilas", "jurnal", 
        "pre-match", "build-up", "preview", "road to", "kick-off show", "warm up", 
        "classic", "rewind", "masterchef", "apa kabar", "lfctv", "mutv", "chelsea tv",
        "(d)", "(r)", "(c)", "hl ", " highlights", "caribbean", "hex", "witchcraft"
    ]
    if any(h in t for h in haram_keywords): return False

    # --- C. DAFTAR HALAL (Ditambah Kualifikasi & Practice Balapan) ---
    halal = [
        "live", "langsung", "liga", "premier", "champions", "fa cup", "serie a", "la liga", 
        "bundesliga", "ligue 1", "eredivisie", "ucl", "uefa", "timnas", "garuda", "badminton", 
        "bwf", "yonex", "masters", "voli", "vnl", "proliga", "motogp", "f1", "nba", "nfl",
        "qualifying", "kualifikasi", "practice", "latihan", " fp1", " fp2", " fp3", " q1", " q2", "sesi"
    ]
    
    return any(x in t for x in halal) or " vs " in t or " v " in t

# ==========================================================
# 3. HUKUM JAM KICK-OFF & DURASI (VERSI DISIPLIN)
# ==========================================================

def is_valid_logic(st, sp, title):
    w, durasi, t = st.hour + (st.minute/60.0), (sp-st).total_seconds()/60, title.lower()

    # --- HUKUM DURASI BOLA ---
    # Jika sepak bola, durasi harus 85-180 menit.
    is_ball = any(x in t for x in ['liga','premier','champions','serie','bundesliga','vs',' v '])
    if is_ball and (durasi < 85 or durasi > 185): return False

    # --- HUKUM BENUA (Cek Jam Kick-off/Sesi Asli) ---
    
    # 1. BADMINTON & RACING (Lolos 24 Jam - Qualifying/Practice ikut masuk)
    if any(k in t for k in ['badminton', 'bwf', 'yonex', 'open', 'masters', 'england', 'motogp', 'f1', 'qualifying', 'practice']):
        return True

    # 2. EROPA (MULAI jam 18:30 - 03:30 WIB)
    eropa = ['premier', 'champions league', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'ucl', 'uefa']
    if any(k in t for k in eropa):
        return True if (w >= 18.5 or w <= 3.5) else False

    # 3. AMERIKA (MULAI jam 02:00 - 11:30 WIB)
    amerika = ['mls', 'major league', 'concacaf', 'libertadores', 'sudamericana', 'brasileiro', 'liga mx', 'nba', 'nfl']
    if any(k in t for k in amerika):
        return True if (2.0 <= w <= 11.5) else False

    # 4. ASIA & INDO (MULAI jam 12:00 - 22:00 WIB)
    asia = ['j-league', 'k-league', 'afc', 'asian', 'aff', 'liga 1', 'bri liga', 'timnas', 'garuda']
    if any(k in t for k in asia):
        return True if (12.0 <= w <= 22.0) else False

    # 5. AFRIKA, ARAB SAUDI & AUSTRALIA
    if any(k in t for k in ['saudi', 'roshn', 'caf ', 'africa']): return True if (w >= 20.0 or w <= 3.0) else False
    if any(k in t for k in ['a-league', 'nrl', 'afl']): return True if (8.0 <= w <= 17.5) else False

    # Penyelamat VS (Sapu Replay Siang)
    return False if (4.0 < w < 13.5) else True

# ==========================================================
# 4. PROSES EKSEKUSI
# ==========================================================

def parse_time(ts):
    try:
        if not ts: return None
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
    except: return None

def main():
    now = datetime.utcnow() + timedelta(hours=7)
    epg_chans, epg_logos, match_data = {}, {}, {}
    limit = (now + timedelta(days=2 if now.hour < 5 else 3)).replace(hour=5, minute=0)
    ses = requests.Session()
    ses.headers.update({'User-Agent': 'Mozilla/5.0'})

    print("Step 1: Sedot EPG...")
    for url in EPG_URLS:
        try:
            r = ses.get(url, timeout=60).content
            root = ET.fromstring(gzip.decompress(r) if r[:2] == b'\x1f\x8b' else r)
            for ch in root.findall("channel"):
                cid, cn = ch.get("id"), ch.findtext("display-name")
                if cid and cn: 
                    epg_chans[cid] = cn.strip()
                    icon = ch.find("icon")
                    if icon is not None: epg_logos[cid] = icon.get("src")
            for pg in root.findall("programme"):
                cid = pg.get("channel")
                if cid not in epg_chans: continue
                title = pg.findtext("title") or ""
                if not is_allowed_content(title, epg_chans[cid]): continue
                st, sp = parse_time(pg.get("start")), parse_time(pg.get("stop"))
                if not st or st >= limit or sp <= now: continue
                if not is_valid_logic(st, sp, title): continue
                
                if cid not in match_data: match_data[cid] = []
                match_data[cid].append({
                    "t": re.sub(r'(?i)(\(l\)|\[l\]|live|langsung)', '', title).strip(),
                    "st": st, "sp": sp, "live": (st-timedelta(minutes=5)) <= now < sp,
                    "logo": (pg.find("icon").get("src") if pg.find("icon") is not None else "")
                })
        except: continue

    print("Step 2: Sedot M3U...")
    res, live_track, up_track = [], set(), set()
    for idx, url in enumerate(MASTER_SOURCES, 1):
        try:
            lines = ses.get(url, timeout=30).text.splitlines()
            block = []
            for ln in lines:
                if not ln.strip() or "EXTM3U" in ln: continue
                if ln.startswith("#"): block.append(ln)
                else:
                    ext = next((t for t in block if "EXTINF" in t), None)
                    if ext and "," in ext:
                        mname = ext.split(",")[-1].strip()
                        for cid, ename in epg_chans.items():
                            en, mn = normalisasi(ename), normalisasi(mname)
                            if en in mn or mn in en:
                                if cid in match_data:
                                    for ev in match_data[cid]:
                                        jam = f"{ev['st'].strftime('%H:%M')}-{ev['sp'].strftime('%H:%M')} WIB"
                                        logo = ev["logo"] or epg_logos.get(cid) or ""
                                        flag = get_flag(mname)
                                        if ev["live"]:
                                            if f"{cid}_{ev['st'].timestamp()}_{ln}" in live_track: continue
                                            live_track.add(f"{cid}_{ev['st'].timestamp()}_{ln}")
                                            res.append({"o":0, "t":ev["st"].timestamp(), "s":ev['t'], "b":[f'#EXTINF:-1 group-title="🔴 ACARA SEDANG TAYANG" tvg-id="{cid}" tvg-logo="{logo}", {flag} 🔴 {jam} - {ev["t"]} [{mname}] ({idx})', ln]})
                                        else:
                                            k_up = f"{ev['st'].strftime('%Y%m%d%H%M')}_{re.sub(r'[^a-z0-9]','',ev['t'].lower())}"
                                            if k_up in up_track: continue
                                            up_track.add(k_up)
                                            lbl = "Besok " if ev['st'].date() == (now.date()+timedelta(days=1)) else "Lusa " if ev['st'].date() == (now.date()+timedelta(days=2)) else ""
                                            res.append({"o":1, "t":ev["st"].timestamp(), "s":ev['t'], "b":[f'#EXTINF:-1 group-title="📅 ACARA AKAN DATANG" tvg-id="{cid}" tvg-logo="{logo}", {flag} ⏳ {lbl}{jam} - {ev["t"]} ({idx})', LINK_UPCOMING]})
                    block = []
        except: continue

    print("Step 3: Simpan...")
    res.sort(key=lambda x: (x["o"], x["t"], x["s"]))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(M3U_HEADER + '\n')
        if not res: f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA JADWAL\n{LINK_STANDBY}\n')
        for item in res: f.write("\n".join(item["b"]) + "\n")

if __name__ == "__main__": main()
