import requests, re, gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import concurrent.futures

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

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

SERVER_PRIORITAS = ['semar', 'lajojo', 'iptv2026']

# BUKU CATATAN PUSAT (SUPER GLOBAL TRACKER)
GLOBAL_SEEN_STREAM_URLS = set()

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
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    bersih = re.sub(r'\s+', ' ', bersih).strip()
    return re.sub(r'^[\-\:\,\|]\s*', '', bersih)

def generate_event_key(title, timestamp):
    # PEMBERSIHAN AGRESIF ANTI-SPAM (Hapus #1, #2, dll)
    title_clean = re.sub(r'(?i)\#\s*\d+', '', title)
    title_clean = re.sub(r'\[.*?\]|\(.*?\)', '', title_clean)
    title_clean = re.sub(r'\d+\]?$', '', title_clean.strip())
    
    judul_norm = REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', title_clean.lower()))
    return f"{judul_norm}_{timestamp}"

def get_channel_number(text):
    nums = REGEX_NUMBERS.findall(text)
    return nums[0] if nums else '0'

def get_priority(url, name):
    teks = (url + " " + name).lower()
    return 0 if any(p in teks for p in SERVER_PRIORITAS) else 1

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

def get_region_ktp(name, epg_id=""):
    n = (name + " " + epg_id).lower()
    if any(x in n for x in ['.us', ' us', 'usa', 'america']): return "US" 
    if any(x in n for x in ['.au', ' au', 'aus', 'optus']): return "AU"
    if any(x in n for x in ['.uk', ' uk', 'eng', 'english', 'sky']): return "UK"
    if any(x in n for x in ['.ae', ' ar', 'arab', 'mena', 'premium', 'ssc']): return "ARAB"
    if any(x in n for x in ['.my', ' my', 'astro', 'malaysia']): return "MY"
    if any(x in n for x in ['.th', ' th', 'thai', 'true']): return "TH"
    if any(x in n for x in ['.sg', ' sg', 'singapore', 'hub']): return "SG"
    if any(x in n for x in ['.za', ' za', 'supersport']): return "ZA"
    if any(x in n for x in ['.hk', ' hk', 'hong']): return "HK"
    if any(x in n for x in ['.ph', ' ph', 'phil']): return "PH"
    if any(x in n for x in ['.id', ' id', 'indo', 'indonesia']): return "ID"
    return "UNKNOWN"

# ==========================================
# III. FILTERING & RULES
# ==========================================
def is_sports_channel(name):
    n = name.lower()
    lokal = ['rcti', 'sctv', 'antv', 'indosiar', 'tvri', 'mnc', 'trans', 'global', 'inews']
    if any(x in n for x in lokal): return True

    sports_keywords = [
        'bein', 'spotv', 'sport', 'soccer', 'champions', 'espn', 'arena bola', 'golf', 'tennis', 'motor', 'fight', 'wwe', 'mola', 'vidio', 'cbs',
        'sky', 'tnt', 'optus', 'hub', 'true premier', 'true sport', 'supersport', 'ss premier', 'ss action', 'ss variety', 'ss grandstand', 
        'dazn', 'setanta', 'eleven', 'now sports', 'fox', 'tsn', 'ssc', 'alkass', 'abu dhabi', 'dubai', 'astro',
        'premier league', 'la liga', 'serie a', 'bundesliga', 'ligue 1', 'nba', 'nfl', 'badminton', 'bwf'
    ]
    return any(x in n for x in sports_keywords)

def is_allowed_sport(title, ch_name, durasi_menit):
    if not title: return False
    t = title.lower()
    c = normalisasi_alias(ch_name)
    
    if REGEX_CYRILLIC_CJK.search(t): return False

    if 'astro' in c:
        haram_astro = ['awani','ria','oasis','prima','rania','citra','hijrah','ceria','warna','shiq','vellithirai','vinmeen','box office', 'a-list']
        if any(x in c for x in haram_astro): return False

    lokal = ['rcti', 'sctv', 'antv', 'indosiar', 'tvri', 'mnc', 'trans', 'global', 'inews']
    if any(x in c for x in lokal) and 'sport' not in c:
        kunci_lokal = [
            'timnas', 'liga 1', 'bri liga', 'indonesia', 'piala', 'afc', 'aff', 'premier', 'champions', 'uefa',
            'badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'open', 'masters', 'tour', 'swiss'
        ]
        if not any(k in t for k in kunci_lokal): return False

    if durasi_menit < 30: return False
    
    bola_keywords = ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v']
    if any(k in c or k in t for k in bola_keywords) and durasi_menit < 85: return False

    haram_simbol = ["(d)", "[d]", "(r)", "[r]", "(c)", "[c]", "hls", "hl ", "h/l", "rev ", "rep ", "del "]
    if any(s in t for s in haram_simbol): return False

    haram_kata = [
        "replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", 
        "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", 
        "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", 
        "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary",
        "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", 
        "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", 
        "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", 
        "sepak mula", "dokumenter", "obrolan", "bincang", "berita", "news", "apa kabar", "religi", 
        "quran", "mekkah", "masterchef", "cgtn", "arirang", "cnn", "lfctv", "mutv", "chelsea tv"
    ]
    if re.search(r'\b(?:' + '|'.join(haram_kata) + r')\b', t): return False

    halal = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", "dutch", "eredivisie",
        "manchester", "madrid", "barcelona", "chelsea", "arsenal", "liverpool", "juventus", "milan", "inter", "bayern", "psg", 
        "indonesia", "bri", "sea games", "asean", "soccer", "football", "copa", "piala", "fifa", "uefa", "mls", "afc", "aff",
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", "yonex", "open", "masters", "tour", "championship", "swiss",
        "voli", "volley", "vnl", "proliga", "futsal", "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint", "nba", "nfl"
    ]
    if re.search(r'\b(?:' + '|'.join(halal).replace('+', r'\+') + r')\b', t) or REGEX_VS.search(t): return True
    return False

def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()

    if any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'open', 'masters', 'tour']): return True
    if any(k in t for k in ['voli', 'volley', 'vnl', 'proliga']): return ((12.0 <= w <= 20.0) or (w >= 22.0 or w <= 4.0) or (5.0 <= w <= 11.0))
    if any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula', 'grand prix', 'sprint']): return ((3.0 <= w <= 6.0) or (9.0 <= w <= 16.0) or (18.0 <= w <= 22.0))
    if any(k in t for k in ['premier', 'champions', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'eredivisie', 'uefa', 'euro', 'carabao', 'copa del rey']): 
        if 6.0 <= w <= 16.5: return False 
        return True
    if any(k in t for k in ['saudi', 'roshn', 'caf', 'africa']): return (w >= 20.0 or w <= 6.5)
    if any(k in t for k in ['j-league', 'k-league', 'afc', 'asian', 'aff']): return (11.5 <= w <= 22.5)
    if any(k in t for k in ['liga 1', 'bri liga', 'indonesia', 'timnas', 'piala presiden']): return (14.0 <= w <= 21.5)
    if any(k in t for k in ['mls', 'major league', 'concacaf', 'libertadores', 'sudamericana', 'liga mx', 'brasileiro', 'nba', 'nfl']): return (2.0 <= w <= 11.5)

    lokal_channels = ['rcti', 'sctv', 'indosiar', 'antv', 'tvri', 'rtv', 'mnc', 'global', 'inews', 'sportstars', 'soccer channel']
    if not any(x in normalisasi_alias(ch_name) for x in lokal_channels):
        if 5.0 < w < 11.0 and " vs " not in t: return False
    return True

def is_match_akurat_v3(epg_name, epg_id, m3u_name):
    e = normalisasi_alias(epg_name).strip()
    m = normalisasi_alias(m3u_name).strip()

    brands = ['bein', 'spotv', 'astro', 'champions tv', 'sportstars', 'soccer channel', 'true premier', 'dazn', 'setanta', 'supersport']
    for b in brands:
        if (b in e) != (b in m): return False

    if 'astro' in e and 'astro' in m:
        subs = ['arena bola 2', 'arena bola', 'arena', 'cricket', 'badminton', 'football', 'golf', 'supersport 1', 'supersport 2', 'supersport 3', 'supersport 4', 'supersport', 'grandstand', 'premier']
        e_sub = next((s for s in subs if s in e), None)
        m_sub = next((s for s in subs if s in m), None)
        if e_sub and m_sub and e_sub != m_sub: return False

    e_clean = re.sub(r'(liga 1|laliga 1|formula 1|f 1|f1|liga 2)', '', e).strip()
    m_clean = re.sub(r'(liga 1|laliga 1|formula 1|f 1|f1|liga 2)', '', m).strip()
    e_k = REGEX_KUALITAS.sub('', e_clean).strip()
    m_k = REGEX_KUALITAS.sub('', m_clean).strip()

    e_num = REGEX_NUMBERS.findall(e_k)
    m_num = REGEX_NUMBERS.findall(m_k)
    en = e_num[0] if e_num else '0'
    mn = m_num[0] if m_num else '0'
    
    pengecualian_angka = ['badminton', 'arena', 'spotv']
    if not any(k in e_k for k in pengecualian_angka):
        if en != mn: return False

    # KUNCIAN KHUSUS NEGARA (PISAHKAN BEIN US, BEIN HK, BEIN ID, DLL)
    ktp_e = get_region_ktp(epg_name, epg_id)
    ktp_m = get_region_ktp(m3u_name)
    
    if 'bein' in e or 'spotv' in e:
        e_reg = ktp_e if ktp_e != "UNKNOWN" else "ID"
        m_reg = ktp_m if ktp_m != "UNKNOWN" else "ID"
        if e_reg != m_reg: return False
    else:
        if ktp_e != "UNKNOWN" and ktp_m != "UNKNOWN" and ktp_e != ktp_m: return False

    if e_k in m_k or m_k in e_k: return True
    
    e_words = set(re.findall(r'[a-z0-9]+', e_k))
    m_words = set(re.findall(r'[a-z0-9]+', m_k))
    if e_words and m_words and (e_words.issubset(m_words) or m_words.issubset(e_words)): return True
    return False

def parse_time(ts):
    if not ts: return None
    try:
        if len(ts) >= 19 and ('+' in ts or '-' in ts):
            dt = datetime.strptime(ts[:20].strip(), "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
    except Exception: return None

# ==========================================
# FUNGSI SEDOT MULTITHREADING
# ==========================================
def fetch_url_content(url, is_epg=False):
    try:
        ses = requests.Session()
        ses.headers.update({'User-Agent': 'Mozilla/5.0'})
        r = ses.get(url, timeout=60).content
        if is_epg:
            return url, (gzip.decompress(r) if r[:2] == b'\x1f\x8b' else r), True
        return url, r.decode('utf-8', errors='ignore'), False
    except Exception as e:
        print(f"  > Gagal mengunduh {url}: {e}")
        return url, None, is_epg

# ==========================================
# IV. PROSES EKSEKUSI UTAMA
# ==========================================
def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    match_data = {}
    epg_chans, epg_logos = {}, {}
    limit_date = now_wib + timedelta(days=3)

    print("Step 1: Sedot Semua EPG & M3U Serentak (Multithreading Turbo)...")
    epg_contents = {}
    m3u_contents = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_url_content, u, True) for u in EPG_URLS]
        futures += [executor.submit(fetch_url_content, u, False) for u in M3U_URLS]
        
        for future in concurrent.futures.as_completed(futures):
            url, content, is_epg = future.result()
            if content:
                if is_epg: epg_contents[url] = content
                else: m3u_contents[url] = content

    print(f"Step 2: Memproses Data EPG (Jadwal 3 Hari Sampai: {limit_date.strftime('%d-%m-%Y %H:%M')} WIB)...")
    for url in EPG_URLS:
        content = epg_contents.get(url)
        if not content: continue
        try:
            root = ET.fromstring(content)
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
                
                judul_bersih = bersihkan_judul_event(title)
                
                if cid not in match_data: match_data[cid] = []
                match_data[cid].append({
                    "title": judul_bersih,
                    "start": st, "stop": sp, "live": is_live, "logo": prog_logo
                })
        except Exception as e:
            print(f"Error parsing XML from {url}: {e}")
            continue

    print("Step 3: Menjahit M3U (Tol Event & Filter 3x3) dengan Global Tracker...")
    keranjang_event_live = {} 
    up_tracker = set()
    
    for url in M3U_URLS:
        content = m3u_contents.get(url)
        if not content: continue
        
        is_event_link = "event_combined.m3u" in url
        lines = content.splitlines()
        block = []
        
        for ln in lines:
            ln_clean = ln.strip()
            if not ln_clean or "EXTM3U" in ln_clean.upper(): continue
            
            if ln_clean.startswith("#"):
                if ln_clean.upper().startswith("#EXTINF"):
                    if any(t.upper().startswith("#EXTINF") for t in block):
                        block = [] 
                block.append(ln_clean) 
            elif len(ln_clean) > 5:
                stream_url = ln_clean
                
                # CEK GLOBAL TRACKER (ANTI DOBEL LINK M3U)
                if stream_url in GLOBAL_SEEN_STREAM_URLS:
                    block = []
                    continue
                GLOBAL_SEEN_STREAM_URLS.add(stream_url)
                
                extinf_idx = next((i for i, t in enumerate(block) if t.upper().startswith("#EXTINF")), -1)
                
                if extinf_idx != -1:
                    raw_extinf = block[extinf_idx]
                    if "," in raw_extinf:
                        raw_attrs, m3u_name = raw_extinf.split(",", 1)
                        m3u_name = m3u_name.strip()
                        
                        logo_match = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_attrs)
                        orig_logo = logo_match.group(1) if logo_match else ""

                        clean_attr = re.sub(r'(?i)\s*(group-title|tvg-group|tvg-id|tvg-logo|tvg-name)=("[^"]*"|\'[^\']*\'|[^\s,]+)', '', raw_attrs).strip()
                        if not clean_attr.upper().startswith("#EXTINF"):
                            clean_attr = "#EXTINF:-1 " + clean_attr.replace('#EXTINF:-1', '').replace('#EXTINF:0', '').strip()
                            
                        bersih_block = [t for t in block if not t.upper().startswith("#EXTGRP")]

                        prioritas_skor = get_priority(stream_url, m3u_name)

                        # JALUR TOL KHUSUS EVENT_COMBINED
                        event_match = REGEX_EVENT.search(m3u_name)
                        if is_event_link and event_match:
                            hh, mm = int(event_match.group(1)), int(event_match.group(2))
                            
                            # BERSIHKAN NAMA DARI #1, #2, dst AGAR TIDAK JADI SPAM
                            event_title_kotor = bersihkan_judul_event(event_match.group(3))
                            event_title = re.sub(r'(?i)\#\s*\d+', '', event_title_kotor)
                            event_title = re.sub(r'\[.*?\]|\(.*?\)', '', event_title)
                            event_title = re.sub(r'\d+\]?$', '', event_title.strip()).strip()
                            
                            if not is_allowed_sport(event_title, "event channel", 100):
                                block = []
                                continue
                            
                            ev_start = now_wib.replace(hour=hh, minute=mm, second=0, microsecond=0)
                            if ev_start < now_wib - timedelta(hours=4): ev_start += timedelta(days=1)
                            ev_stop = ev_start + timedelta(hours=2) 
                            
                            if not is_valid_time(ev_start, event_title, "event channel"):
                                block = []
                                continue

                            if ev_stop <= now_wib or ev_start >= limit_date:
                                block = []
                                continue
                                
                            is_live = (ev_start - timedelta(minutes=5)) <= now_wib < ev_stop
                            jam = f"{ev_start.strftime('%H:%M')}-{ev_stop.strftime('%H:%M')} WIB"
                            flag = get_flag(event_title)
                            
                            event_key = generate_event_key(event_title, ev_start.timestamp())
                            
                            if is_live:
                                if event_key not in keranjang_event_live: keranjang_event_live[event_key] = {}
                                if "EVENT_VIP" not in keranjang_event_live[event_key]:
                                    if len(keranjang_event_live[event_key]) >= 3: 
                                        block = []
                                        continue 
                                    keranjang_event_live[event_key]["EVENT_VIP"] = []
                                
                                judul = f"{flag} 🔴 {jam} - {event_title} [Live Event]"
                                live_block = list(bersih_block) 
                                live_block[extinf_idx] = f'{clean_attr} group-title="🔴 SEDANG TAYANG" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                                
                                keranjang_event_live[event_key]["EVENT_VIP"].append({
                                    "order": 0, "sort": ev_start.timestamp(), "prioritas": prioritas_skor, "data": live_block + [stream_url]
                                })
                            else:
                                if event_key in up_tracker: 
                                    block = []
                                    continue
                                up_tracker.add(event_key)
                                
                                ev_date = ev_start.date()
                                hari_ini = now_wib.date()
                                if ev_date == hari_ini + timedelta(days=1): lbl = "Besok "
                                elif ev_date == hari_ini + timedelta(days=2): lbl = "Lusa "
                                elif ev_date > hari_ini + timedelta(days=2): lbl = f"{ev_start.strftime('%d/%m')} "
                                else: lbl = ""
                                
                                judul = f"{flag} ⏳ {lbl}{jam} - {event_title} [Live Event]"
                                up_extinf = f'{clean_attr} group-title="📅 AKAN TAYANG" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                                
                                if event_key not in keranjang_event_live: keranjang_event_live[event_key] = {}
                                keranjang_event_live[event_key]["UPCOMING"] = [{
                                    "order": 1, "sort": ev_start.timestamp(), "prioritas": 0, "data": [up_extinf, LINK_UPCOMING]
                                }]
                                
                            block = []
                            continue 

                        # JALUR NORMAL (SPORTS & INDONESIA COMBINED)
                        if is_sports_channel(m3u_name):
                            flag = get_flag(m3u_name)
                            matched_cid = None
                            
                            for cid, ename in epg_chans.items():
                                if is_match_akurat_v3(ename, cid, m3u_name):
                                    matched_cid = cid
                                    break
                            
                            if matched_cid and matched_cid in match_data:
                                for ev in match_data[matched_cid]:
                                    jam = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')} WIB"
                                    final_logo = ev['logo'] if ev.get('logo') else (epg_logos.get(matched_cid) if epg_logos.get(matched_cid) else orig_logo)
                                    
                                    event_key = generate_event_key(ev['title'], ev['start'].timestamp())
                                    
                                    if ev["live"]:
                                        if event_key not in keranjang_event_live: keranjang_event_live[event_key] = {}
                                        
                                        if matched_cid not in keranjang_event_live[event_key]:
                                            if len(keranjang_event_live[event_key]) >= 3: continue 
                                            keranjang_event_live[event_key][matched_cid] = []
                                        
                                        judul = f"{flag} 🔴 {jam} - {ev['title']} [{m3u_name}]"
                                        live_block = list(bersih_block) 
                                        live_block[extinf_idx] = f'{clean_attr} group-title="🔴 SEDANG TAYANG" tvg-id="{matched_cid}" tvg-logo="{final_logo}", {judul}'
                                        
                                        keranjang_event_live[event_key][matched_cid].append({
                                            "order": 0, "sort": ev['start'].timestamp(), "prioritas": prioritas_skor, "data": live_block + [stream_url]
                                        })
                                    else:
                                        if event_key in up_tracker: continue
                                        up_tracker.add(event_key)
                                        
                                        ev_date = ev['start'].date()
                                        hari_ini = now_wib.date()
                                        if ev_date == hari_ini + timedelta(days=1): lbl = "Besok "
                                        elif ev_date == hari_ini + timedelta(days=2): lbl = "Lusa "
                                        elif ev_date > hari_ini + timedelta(days=2): lbl = f"{ev['start'].strftime('%d/%m')} "
                                        else: lbl = ""
                                        
                                        judul = f"{flag} ⏳ {lbl}{jam} - {ev['title']} [{m3u_name}]"
                                        up_extinf = f'{clean_attr} group-title="📅 AKAN TAYANG" tvg-id="{matched_cid}" tvg-logo="{final_logo}", {judul}'
                                        
                                        if event_key not in keranjang_event_live: keranjang_event_live[event_key] = {}
                                        keranjang_event_live[event_key]["UPCOMING"] = [{
                                            "order": 1, "sort": ev['start'].timestamp(), "prioritas": 0, "data": [up_extinf, LINK_UPCOMING]
                                        }]
                                        
                block = [] 

    print("Step 4: Membatasi Max 3 Server dan Rendering Playlist...")
    hasil_m3u = []
    
    for event_key, channels in keranjang_event_live.items():
        for cid, daftar_link in channels.items():
            daftar_link.sort(key=lambda x: x["prioritas"])
            top_3 = daftar_link[:3]
            hasil_m3u.extend(top_3)

    hasil_m3u.sort(key=lambda x: (x["order"], float(x["sort"])))
    
    # EPG GLOBAL DIHILANGKAN DARI HEADER AGAR APLIKASI TV LEBIH RINGAN
    m3u_header = f'#EXTM3U name="🔴 BAKUL WIFI SPORTS (Upd: {now_wib.strftime("%H:%M WIB")})"\n'
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_header)
        if not hasil_m3u: 
            f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA PERTANDINGAN\n{LINK_STANDBY}\n')
        for item in hasil_m3u: 
            f.write("\n".join(item["data"]) + "\n")

    print(f"Selesai! {len(hasil_m3u)} Jadwal (Full Fitur) Siap Meluncur.")

if __name__ == "__main__": main()
