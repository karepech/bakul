import requests, re, gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ==========================================
# I. KONFIGURASI EMAS (MULTI-EPG & M3U VIP)
# ==========================================
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"                   
]

M3U_URLS = [
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/indonesia_combined.m3u"
]

GLOBAL_EPG_URL = "https://www.open-epg.com/generate/bXxbrwUThe.xml"
OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

# ==========================================
# II. OPTIMASI REGEX & FUNGSI PEMBANTU
# ==========================================
REGEX_CHAMPIONS = re.compile(r'\b(?:champions?\s*tv|champions?|ctv)\s*(\d+)\b')
REGEX_STARS = re.compile(r'\bsports?\s+stars?\b')
REGEX_MNC = re.compile(r'\bmnc\s*sports?\b')
REGEX_SPO = re.compile(r'\bspo\s+tv\b')
REGEX_CYRILLIC_CJK = re.compile(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]')
REGEX_KUALITAS = re.compile(r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|network|premium|now)\b')
REGEX_NUMBERS = re.compile(r'\d+')
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')

def get_channel_number(text):
    nums = REGEX_NUMBERS.findall(text)
    return nums[0] if nums else '0' # [PERBAIKAN] Ambil angka depan yang relevan

def normalisasi_alias(name):
    if not name: return ""
    n = name.lower().strip()
    n = REGEX_CHAMPIONS.sub(r'champions tv \1', n)
    n = REGEX_STARS.sub('sportstars', n) 
    n = REGEX_MNC.sub('sportstars', n)    
    n = REGEX_SPO.sub('spotv', n)              
    return n

def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'astro', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    if any(x in n for x in [' ae', 'arab', 'mena']): return "🇸🇦"
    
    if 'bein' in n and not any(x in n for x in [' en', ' hk', ' th', ' ph', ' my', ' sg', ' au', ' arab']): return "🇮🇩"
    if any(x in n for x in [' id', 'indo', 'vidio', 'rcti', 'sctv', 'mnc', 'tvri', 'antv', 'indosiar', 'rtv', 'inews']): return "🇮🇩"
    return "📺" 

def get_region_ktp(name, epg_id=""):
    n = name.lower() + " " + epg_id.lower()
    if any(x in n for x in ['.au', ' au', 'aus', 'optus']): return "AU"
    if any(x in n for x in ['.uk', ' uk', 'eng', 'english']): return "UK"
    if any(x in n for x in ['.ae', ' ar', 'arab', 'mena', 'premium']): return "ARAB"
    if any(x in n for x in ['.my', ' my', 'astro', 'malaysia']): return "MY"
    if any(x in n for x in ['.th', ' th', 'thai', 'true']): return "TH"
    if any(x in n for x in ['.sg', ' sg', 'singapore', 'hub']): return "SG"
    if any(x in n for x in ['bein', 'spotv', 'id', 'indo']): return "ID"
    return "UNKNOWN"

# ==========================================
# III. FILTERING & RULES
# ==========================================
def is_sports_channel(name):
    n = name.lower()
    
    # Aturan TV Lokal (Hanya diloloskan jika ada kata 'sport')
    lokal = ['rcti', 'sctv', 'antv', 'indosiar', 'tvri', 'mnc', 'trans', 'global', 'inews']
    if any(x in n for x in lokal):
        return 'sport' in n

    # Aturan Astro
    if 'astro' in n:
        haram = ['awani','ria','oasis','prima','rania','citra','hijrah','ceria','warna','shiq','vellithirai','vinmeen','box office', 'a-list']
        if any(x in n for x in haram): return False
        halal_astro = ['arena', 'supersport', 'grandstand', 'premier', 'cricket', 'badminton', 'football', 'golf', 'tennis', 'rugby', 'sport']
        return any(x in n for x in halal_astro)

    sports_keywords = ['bein', 'spotv', 'sport', 'soccer', 'champions', 'espn', 'arena bola', 'golf', 'tennis', 'motor', 'fight', 'wwe', 'tnt', 'sky', 'optus', 'hub', 'mola', 'vidio', 'cbs']
    return any(x in n for x in sports_keywords)

def is_allowed_sport(title, ch_name, durasi_menit):
    if not title: return False
    t = title.lower()
    c = normalisasi_alias(ch_name)
    
    if REGEX_CYRILLIC_CJK.search(t): return False

    # JALUR VVIP ASTRO BADMINTON [PERBAIKAN: Penambahan open, tour, championship]
    if 'astro arena' in c or 'astro badminton' in c:
        if not any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'master', 'open', 'tour', 'championship']): 
            return False

    # HUKUM DURASI & KATA HARAM
    if durasi_menit < 30: return False
    
    bola_keywords = ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v']
    is_football = any(k in c or k in t for k in bola_keywords)
    if is_football and durasi_menit < 85: return False

    haram = [
        "(d)", "[d]", "(r)", "[r]", "(c)", "[c]", "hls", "hl ", "h/l", "rev ", "rep ", "del ",
        "replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", 
        "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", 
        "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", 
        "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary",
        "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", 
        "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", 
        "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", 
        "sepak mula", "dokumenter", "obrolan", "bincang",
        "berita", "news", "apa kabar", "religi", "quran", "mekkah", "masterchef", "cgtn", "arirang", 
        "cnn", "lfctv", "mutv", "chelsea tv"
    ]
    if re.search(r'\b(?:' + '|'.join(haram).replace('+', r'\+') + r')\b', t): return False

    halal = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", "dutch", "eredivisie",
        "manchester", "madrid", "barcelona", "chelsea", "arsenal", "liverpool", "juventus", "milan", "inter", "bayern", "psg", 
        "indonesia", "bri", "sea games", "asean", "soccer", "football", "copa", "piala", "fifa", "uefa", "mls", "afc", "aff",
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", "yonex", "open", "masters", "tour", "championship",
        "voli", "volley", "vnl", "proliga", "futsal",
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint", "nba", "nfl"
    ]
    if re.search(r'\b(?:' + '|'.join(halal).replace('+', r'\+') + r')\b', t) or REGEX_VS.search(t):
        return True
        
    return False

def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()

    if any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'open', 'masters', 'tour']): return True
    
    if any(k in t for k in ['voli', 'volley', 'vnl', 'proliga']):
        if (12.0 <= w <= 20.0) or (w >= 22.0 or w <= 4.0) or (5.0 <= w <= 11.0): return True
        return False

    if any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula', 'grand prix', 'sprint']):
        if (3.0 <= w <= 6.0) or (9.0 <= w <= 16.0) or (18.0 <= w <= 22.0): return True
        return False

    if any(k in t for k in ['premier', 'champions', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'eredivisie', 'uefa', 'euro', 'carabao', 'copa del rey']):
        if w >= 18.0 or w <= 5.0: return True
        return False 

    if any(k in t for k in ['saudi', 'roshn', 'caf', 'africa']):
        if w >= 20.0 or w <= 6.5: return True
        return False

    if any(k in t for k in ['j-league', 'k-league', 'afc', 'asian', 'aff']):
        if 11.5 <= w <= 22.5: return True
        return False 

    if any(k in t for k in ['liga 1', 'bri liga', 'indonesia', 'timnas', 'piala presiden']):
        if 14.0 <= w <= 21.5: return True
        return False 

    if any(k in t for k in ['mls', 'major league', 'concacaf', 'libertadores', 'sudamericana', 'liga mx', 'brasileiro', 'nba', 'nfl']):
        if 2.0 <= w <= 11.5: return True
        return False 

    lokal_channels = ['rcti', 'sctv', 'indosiar', 'antv', 'tvri', 'rtv', 'mnc', 'global', 'inews', 'sportstars', 'soccer channel']
    if not any(x in normalisasi_alias(ch_name) for x in lokal_channels):
        if 5.0 < w < 11.0 and " vs " not in t: 
            return False

    return True

# --- MESIN PENCOCOKAN KETAT ---
def is_match_akurat_v2(epg_name, epg_id, m3u_name):
    e = REGEX_KUALITAS.sub('', normalisasi_alias(epg_name)).strip()
    m = REGEX_KUALITAS.sub('', normalisasi_alias(m3u_name)).strip()
    
    if get_channel_number(e) != get_channel_number(m): return False

    # Filter Anti-Kloning Ekstra Ketat (Xtra, Now, Max, Plus)
    for net in ['xtra', 'extra', 'now', 'max', 'plus']:
        if (net in e) != (net in m): return False

    # Filter KTP Negara
    ktp_e = get_region_ktp(epg_name, epg_id)
    ktp_m = get_region_ktp(m3u_name)
    if ktp_e != "UNKNOWN" and ktp_m != "UNKNOWN" and ktp_e != ktp_m: return False

    if e in m or m in e: return True
    
    e_words = set(re.findall(r'[a-z0-9]+', e))
    m_words = set(re.findall(r'[a-z0-9]+', m))
    if e_words and m_words and (e_words.issubset(m_words) or m_words.issubset(e_words)): 
        return True
        
    return False

def parse_time(ts):
    if not ts: return None
    try:
        if len(ts) >= 19 and ('+' in ts or '-' in ts):
            dt = datetime.strptime(ts[:20].strip(), "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
    except Exception:
        return None

# ==========================================
# IV. PROSES EKSEKUSI UTAMA
# ==========================================
def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    match_data = {}
    epg_chans, epg_logos = {}, {}
    limit_date = now_wib + timedelta(hours=24)

    ses = requests.Session()
    ses.headers.update({'User-Agent': 'Mozilla/5.0'})

    print(f"Step 1: Sedot EPG (Jadwal 24 Jam Sampai: {limit_date.strftime('%d-%m-%Y %H:%M')} WIB)...")
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
                
                st, sp = parse_time(pg.get("start")), parse_time(pg.get("stop"))
                if not st or not sp or sp <= now_wib or st >= limit_date: continue 
                
                durasi_menit = (sp - st).total_seconds() / 60
                title = pg.findtext("title") or ""
                ch_name = epg_chans[cid]
                
                if not is_allowed_sport(title, ch_name, durasi_menit): continue
                if not is_valid_time(st, title, ch_name): continue
                
                is_live = (st - timedelta(minutes=5)) <= now_wib < sp
                prog_logo = pg.find("icon").get("src") if pg.find("icon") is not None else ""
                
                if cid not in match_data: match_data[cid] = []
                match_data[cid].append({
                    "title": REGEX_LIVE.sub('', title).strip(),
                    "start": st, "stop": sp, "live": is_live, "logo": prog_logo
                })
        except Exception: continue

    print("Step 2: Menjahit M3U (Full Blok & Verifikasi Ketat)...")
    hasil_m3u = []
    up_tracker = set()
    
    for idx, url in enumerate(M3U_URLS, 1):
        try:
            lines = ses.get(url, timeout=30).text.splitlines()
            block = []
            for ln in lines:
                ln_clean = ln.strip()
                if not ln_clean or "EXTM3U" in ln_clean.upper(): continue
                
                if ln_clean.startswith("#"):
                    if ln_clean.upper().startswith("#EXTINF"):
                        if any(t.upper().startswith("#EXTINF") for t in block):
                            block = [] 
                    block.append(ln_clean) 
                else:
                    stream_url = ln_clean
                    extinf_idx = next((i for i, t in enumerate(block) if t.upper().startswith("#EXTINF")), -1)
                    
                    if extinf_idx != -1:
                        raw_extinf = block[extinf_idx]
                        if "," in raw_extinf:
                            raw_attrs, m3u_name = raw_extinf.split(",", 1)
                            m3u_name = m3u_name.strip()
                            
                            if is_sports_channel(m3u_name):
                                logo_match = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_attrs)
                                orig_logo = logo_match.group(1) if logo_match else ""

                                clean_attr = re.sub(r'(?i)\s*(group-title|tvg-id|
