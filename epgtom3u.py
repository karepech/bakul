import requests, re, gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import concurrent.futures
from functools import lru_cache

# ==========================================
# I. KONFIGURASI EMAS (MULTI-EPG & M3U VIP)
# ==========================================
MAP_URL = "https://raw.githubusercontent.com/karepech/bakul/refs/heads/main/map.txt"

EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"                   
]

# File indonesia_combined resmi dihapus agar STB tidak berat
M3U_URLS = [
    "https://bit.ly/KPL203",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
]

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 
SERVER_PRIORITAS = ['semar', 'lajojo', 'iptv2026']

GLOBAL_SEEN_STREAM_URLS = set()
MAPPING_DICT = {}
COMPILED_MAPPING = []

# ==========================================
# II. SISTEM MAPPING / KAMUS PINTAR (TURBO)
# ==========================================
def load_mapping():
    global MAPPING_DICT, COMPILED_MAPPING
    try:
        print("Mengambil Kamus Pintar (map.txt)...")
        r = requests.get(MAP_URL, timeout=30).text
        for line in r.splitlines():
            line = line.split('#')[0].strip() 
            if not line or line.startswith('['): continue
            if '=' in line:
                official, aliases = line.split('=', 1)
                official = official.strip().lower()
                for alias in aliases.split(','):
                    alias = alias.strip().lower()
                    if alias:
                        MAPPING_DICT[alias] = official
        
        MAPPING_DICT = dict(sorted(MAPPING_DICT.items(), key=lambda x: len(x[0]), reverse=True))
        for alias, official in MAPPING_DICT.items():
            COMPILED_MAPPING.append((re.compile(r'\b' + re.escape(alias) + r'\b'), official))
        print(f"  > Berhasil menghafal {len(MAPPING_DICT)} istilah!")
    except Exception as e:
        print(f"  > Gagal memuat map.txt: {e}")

@lru_cache(maxsize=None)
def terjemahkan_nama(teks):
    if not teks: return ""
    n = teks.lower().strip()
    for pattern, official in COMPILED_MAPPING:
        n = pattern.sub(official, n)
    return n

# ==========================================
# III. OPTIMASI REGEX & FUNGSI PEMBANTU
# ==========================================
REGEX_CYRILLIC_CJK = re.compile(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]')
REGEX_KUALITAS = re.compile(r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|network|premium|now)\b')
REGEX_NUMBERS = re.compile(r'\d+')
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

@lru_cache(maxsize=10000)
def generate_event_key(title, timestamp):
    title_clean = re.sub(r'(?i)\#\s*\d+', '', title)
    title_clean = re.sub(r'\[.*?\]|\(.*?\)', '', title_clean)
    title_clean = re.sub(r'\d+\]?$', '', title_clean.strip())
    judul_norm = REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', title_clean.lower()))
    return f"{judul_norm}_{timestamp}"

# SKOR VVIP: Mengatur agar beIN & Lokal naik ke urutan teratas
@lru_cache(maxsize=5000)
def get_vip_score(ch_name):
    n = ch_name.lower()
    vip_keywords = ['bein', 'spotv', 'sportstars', 'soccer channel', 'champions tv', 'rcti sports', 'inews sports', 'mnc sports']
    if any(k in n for k in vip_keywords):
        return 0
    return 1

@lru_cache(maxsize=5000)
def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' us', 'usa', 'america']): return "🇺🇸" 
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'astro', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk', 'sky']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai', 'true']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    if any(x in n for x in [' ae', 'arab', 'mena', 'ssc', 'alkass', 'abu dhabi']): return "🇸🇦"
    if any(x in n for x in [' za', 'supersport', 'africa']): return "🇿🇦"
    if any(x in n for x in [' id', 'indo', 'indonesia', 'vidio', 'rcti', 'sctv', 'mnc', 'tvri', 'antv', 'indosiar', 'rtv', 'inews']): return "🇮🇩"
    if 'bein' in n and not any(x in n for x in [' us', ' usa', ' sg', ' my', ' uk', ' th', ' hk', ' au', ' ae', ' za', ' ph']): return "🇮🇩"
    return "📺" 

# ==========================================
# IV. FILTERING & ATURAN VVIP
# ==========================================
@lru_cache(maxsize=10000)
def is_sports_channel(name):
    n = terjemahkan_nama(name)
    lokal = ['rcti', 'sctv', 'antv', 'indosiar', 'tvri', 'mnc', 'trans', 'global', 'inews']
    if any(x in n for x in lokal) and 'soccer channel' not in n:
        return 'sport' in n
    sports_keywords = ['bein', 'spotv', 'sport', 'soccer', 'champions', 'espn', 'arena bola', 'golf', 'tennis', 'motor', 'fight', 'wwe', 'mola', 'vidio', 'cbs', 'sky', 'tnt', 'optus', 'hub', 'true premier', 'supersport', 'dazn', 'setanta', 'eleven', 'now sports', 'fox', 'tsn', 'ssc', 'alkass', 'abu dhabi', 'dubai', 'astro']
    return any(x in n for x in sports_keywords)

def is_allowed_sport(title, ch_name, durasi_menit):
    if not title: return False
    t = terjemahkan_nama(title)
    if REGEX_CYRILLIC_CJK.search(t) or durasi_menit < 30: return False
    haram_kata = ["replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary", "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", "sepak mula", "dokumenter", "obrolan", "bincang", "berita", "news", "apa kabar", "religi", "quran", "mekkah", "masterchef", "cgtn", "arirang", "cnn", "lfctv", "mutv", "chelsea tv"]
    if re.search(r'\b(?:' + '|'.join(haram_kata) + r')\b', t): return False
    return True

def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = terjemahkan_nama(title)
    if any(k in t for k in ['badminton', 'bwf', 'motogp', 'f1']): return True
    if any(k in t for k in ['premier', 'champions', 'serie a', 'la liga', 'bundesliga', 'ligue 1']): 
        if 6.0 <= w <= 13.5: return False 
    return True

@lru_cache(maxsize=10000)
def is_match_akurat_v3(epg_name, epg_id, m3u_name):
    e = terjemahkan_nama(epg_name)
    m = terjemahkan_nama(m3u_name)
    brands = ['bein', 'spotv', 'astro', 'champions tv', 'sportstars', 'soccer channel', 'true premier', 'dazn', 'setanta', 'supersport']
    for b in brands:
        if (b in e) != (b in m): return False
    e_clean = re.sub(r'(liga 1|laliga 1|formula 1|f 1|f1|liga 2)', '', e).strip()
    m_clean = re.sub(r'(liga 1|laliga 1|formula 1|f 1|f1|liga 2)', '', m).strip()
    e_k = REGEX_KUALITAS.sub('', e_clean).strip()
    m_k = REGEX_KUALITAS.sub('', m_clean).strip()
    e_num = REGEX_NUMBERS.findall(e_k)
    m_num = REGEX_NUMBERS.findall(m_k)
    en = e_num[0] if e_num else '0'
    mn = m_num[0] if m_num else '0'
    if not any(k in e_k for k in ['badminton', 'arena', 'spotv']):
        if en != mn: return False
    return True

# ==========================================
# VI. PROSES EKSEKUSI UTAMA
# ==========================================
def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    match_data, epg_chans, epg_logos = {}, {}, {}
    besok = now_wib + timedelta(days=1)
    limit_date = besok.replace(hour=23, minute=59, second=59)

    load_mapping()
    
    print("Step 1: Sedot EPG & M3U...")
    epg_contents, m3u_contents = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_url_content, u, True) for u in EPG_URLS]
        futures += [executor.submit(fetch_url_content, u, False) for u in M3U_URLS]
        for f in concurrent.futures.as_completed(futures):
            url, content, is_epg = f.result()
            if content:
                if is_epg: epg_contents[url] = content
                else: m3u_contents[url] = content

    print("Step 2: Proses EPG...")
    for content in epg_contents.values():
        try:
            root = ET.fromstring(content)
            for ch in root.findall("channel"):
                cid, cn = ch.get("id"), ch.findtext("display-name")
                if cid and cn and is_sports_channel(cn): 
                    epg_chans[cid] = cn.strip()
                    icon = ch.find("icon")
                    if icon is not None: epg_logos[cid] = icon.get("src")
            for pg in root.findall("programme"):
                cid = pg.get("channel")
                if cid not in epg_chans: continue 
                st, sp = parse_time(pg.get("start")), parse_time(pg.get("stop"))
                if not st or not sp or sp <= now_wib or st >= limit_date: continue 
                durasi = (sp - st).total_seconds() / 60
                title = pg.findtext("title") or ""
                if is_allowed_sport(title, epg_chans[cid], durasi) and is_valid_time(st, title, epg_chans[cid]):
                    if cid not in match_data: match_data[cid] = []
                    match_data[cid].append({"title": re.sub(r'\s+', ' ', REGEX_LIVE.sub('', title)).strip(), "start": st, "stop": sp, "live": (st - timedelta(minutes=5)) <= now_wib < sp, "logo": pg.find("icon").get("src") if pg.find("icon") is not None else ""})
        except: continue

    print("Step 3: Jahit M3U (Ultra-Light STB)...")
    keranjang_event_live, up_tracker = {}, set()
    for url, content in m3u_contents.items():
        lines = content.splitlines()
        block = []
        for ln in lines:
            ln = ln.strip()
            if not ln or "EXTM3U" in ln.upper(): continue
            if ln.startswith("#"):
                if ln.upper().startswith("#EXTINF"): block = [ln]
                else: block.append(ln)
            else:
                if not block: continue
                raw_extinf = block[0]
                if "KPL203" in url and not re.search(r'(?i)group-title=["\'][^"\']*event', raw_extinf): 
                    block = []
                    continue
                if "," in raw_extinf:
                    m3u_name = raw_extinf.split(",", 1)[1].strip()
                    logo_match = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_extinf)
                    orig_logo = logo_match.group(1) if logo_match else ""
                    skor_vip = get_vip_score(m3u_name)
                    
                    # JALUR TOL JAM
                    ev_m = REGEX_EVENT.search(m3u_name)
                    if ev_m:
                        hh, mm = int(ev_m.group(1)), int(ev_m.group(2))
                        ev_title = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', ev_m.group(3)).strip()
                        ev_start = now_wib.replace(hour=hh, minute=mm, second=0, microsecond=0)
                        if ev_start < now_wib - timedelta(hours=4): ev_start += timedelta(days=1)
                        if ev_start < limit_date:
                            is_live = (ev_start - timedelta(minutes=5)) <= now_wib < (ev_start + timedelta(hours=2))
                            key = generate_event_key(ev_title, ev_start.timestamp())
                            judul = f"{get_flag(ev_title)} {'🔴' if is_live else '⏳'} {'' if is_live or ev_start.date() == now_wib.date() else 'Besok'} {ev_start.strftime('%H:%M')} - {ev_title}"
                            inf = f'#EXTINF:-1 group-title="{"🔴 SEDANG TAYANG" if is_live else "📅 AKAN TAYANG"}" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                            if is_live:
                                if key not in keranjang_event_live: keranjang_event_live[key] = {"EVENT_VIP": []}
                                keranjang_event_live[key]["EVENT_VIP"].append({"order": 0, "vip_score": skor_vip, "sort": ev_start.timestamp(), "prioritas": 0, "data": [inf, ln]})
                            elif key not in up_tracker:
                                up_tracker.add(key)
                                if key not in keranjang_event_live: keranjang_event_live[key] = {"UPCOMING": []}
                                keranjang_event_live[key]["UPCOMING"].append({"order": 1, "vip_score": skor_vip, "sort": ev_start.timestamp(), "prioritas": 0, "data": [inf, f"{LINK_UPCOMING}?match={key}"]})
                    # JALUR EPG
                    elif is_sports_channel(m3u_name):
                        for cid, ename in epg_chans.items():
                            if is_match_akurat_v3(ename, cid, m3u_name) and cid in match_data:
                                for ev in match_data[cid]:
                                    key = generate_event_key(ev['title'], ev['start'].timestamp())
                                    judul = f"{get_flag(m3u_name)} {'🔴' if ev['live'] else '⏳'} {'' if ev['live'] or ev['start'].date() == now_wib.date() else 'Besok'} {ev['start'].strftime('%H:%M')} - {ev['title']} [{re.sub(r'[\[\]\(\)]', '', m3u_name).strip()}]"
                                    inf = f'#EXTINF:-1 group-title="{"🔴 SEDANG TAYANG" if ev["live"] else "📅 AKAN TAYANG"}" tvg-id="{cid}" tvg-logo="{ev["logo"] or epg_logos.get(cid) or orig_logo}", {judul}'
                                    if ev["live"]:
                                        if key not in keranjang_event_live: keranjang_event_live[key] = {}
                                        if cid not in keranjang_event_live[key]: keranjang_event_live[key][cid] = []
                                        keranjang_event_live[key][cid].append({"order": 0, "vip_score": skor_vip, "sort": ev['start'].timestamp(), "prioritas": get_priority(ln, m3u_name), "data": [inf, ln]})
                                    elif key not in up_tracker:
                                        up_tracker.add(key)
                                        if key not in keranjang_event_live: keranjang_event_live[key] = {"UPCOMING": []}
                                        keranjang_event_live[key]["UPCOMING"].append({"order": 1, "vip_score": skor_vip, "sort": ev['start'].timestamp(), "prioritas": 0, "data": [inf, f"{LINK_UPCOMING}?match={key}"]})
                block = []

    print("Step 4: Rendering...")
    hasil = []
    for chan_dict in keranjang_event_live.values():
        for cid, links in chan_dict.items():
            links.sort(key=lambda x: x["prioritas"])
            hasil.extend(links[:3])
    hasil.sort(key=lambda x: (x["order"], float(x["sort"]), x["vip_score"]))
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f'#EXTM3U name="🔴 BAKUL WIFI SPORTS (Upd: {now_wib.strftime("%H:%M WIB")})"\n')
        if not hasil: f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA PERTANDINGAN\n{LINK_STANDBY}\n')
        for it in hasil: f.write("\n".join(it["data"]) + "\n")

def fetch_url_content(url, is_epg=False):
    try:
        r = requests.get(url, timeout=60).content
        return url, (gzip.decompress(r) if r[:2] == b'\x1f\x8b' else r.decode('utf-8', errors='ignore')), is_epg
    except: return url, None, is_epg

def parse_time(ts):
    try: return datetime.strptime(ts[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
    except: return None

if __name__ == "__main__": main()
