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

# File indonesia_combined dihapus sesuai perintah agar super ringan!
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
            
        print(f"  > Berhasil menghafal dan mengkompilasi {len(MAPPING_DICT)} istilah!")
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
def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    bersih = re.sub(r'\s+', ' ', bersih).strip()
    return re.sub(r'^[\-\:\,\|]\s*', '', bersih)

@lru_cache(maxsize=10000)
def generate_event_key(title, timestamp):
    title_clean = re.sub(r'(?i)\#\s*\d+', '', title)
    title_clean = re.sub(r'\[.*?\]|\(.*?\)', '', title_clean)
    title_clean = re.sub(r'\d+\]?$', '', title_clean.strip())
    judul_norm = REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', title_clean.lower()))
    return f"{judul_norm}_{timestamp}"

def get_priority(url, name):
    teks = (url + " " + name).lower()
    return 0 if any(p in teks for p in SERVER_PRIORITAS) else 1

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

@lru_cache(maxsize=5000)
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
# IV. FILTERING & ATURAN VVIP
# ==========================================
@lru_cache(maxsize=10000)
def is_sports_channel(name):
    n = terjemahkan_nama(name)
    lokal = ['rcti', 'sctv', 'antv', 'indosiar', 'tvri', 'mnc', 'trans', 'global', 'inews']
    if any(x in n for x in lokal) and 'soccer channel' not in n:
        return 'sport' in n

    if 'astro' in n:
        haram = ['awani','ria','oasis','prima','rania','citra','hijrah','ceria','warna','shiq','vellithirai','vinmeen','box office', 'a-list']
        if any(x in n for x in haram): return False
        return True 

    sports_keywords = [
        'bein', 'spotv', 'sport', 'soccer', 'champions', 'espn', 'arena bola', 'golf', 'tennis', 'motor', 'fight', 'wwe', 'mola', 'vidio', 'cbs',
        'sky', 'tnt', 'optus', 'hub', 'true premier', 'true sport', 'supersport', 'ss premier', 'ss action', 'ss variety', 'ss grandstand', 
        'dazn', 'setanta', 'eleven', 'now sports', 'fox', 'tsn', 'ssc', 'alkass', 'abu dhabi', 'dubai', 'astro'
    ]
    return any(x in n for x in sports_keywords)

def is_allowed_sport(title, ch_name, durasi_menit):
    if not title: return False
    
    t = terjemahkan_nama(title)
    c = terjemahkan_nama(ch_name)
    
    if REGEX_CYRILLIC_CJK.search(t): return False

    # ATURAN DURASI 85 MENIT TELAH DIMUSNAHKAN! Hanya filter short highlights (< 30 mnt).
    if durasi_menit < 30: return False

    haram_simbol = ["(d)", "[d]", "(r)", "[r]", "(c)", "[c]", "hls", "hl ", "h/l", "rev ", "rep ", "del "]
    if any(s in t for s in haram_simbol): return False

    haram_kata = ["replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary", "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", "sepak mula", "dokumenter", "obrolan", "bincang", "berita", "news", "apa kabar", "religi", "quran", "mekkah", "masterchef", "cgtn", "arirang", "cnn", "lfctv", "mutv", "chelsea tv"]
    if re.search(r'\b(?:' + '|'.join(haram_kata) + r')\b', t): return False

    return True

def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = terjemahkan_nama(title)

    if any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'open', 'masters', 'tour']): return True
    if any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula', 'grand prix', 'sprint']): return True
    
    if any(k in t for k in ['premier', 'champions', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'eredivisie', 'uefa', 'euro', 'carabao', 'copa del rey']): 
        if 6.0 <= w <= 13.5: return False 
        return True
        
    if any(k in t for k in ['mls', 'major league', 'concacaf', 'libertadores', 'sudamericana', 'liga mx', 'brasileiro', 'nba', 'nfl']): 
        if 13.0 <= w <= 23.0: return False 
        return True

    if any(k in t for k in ['j-league', 'k-league', 'afc', 'asian', 'aff', 'liga 1', 'bri liga', 'indonesia', 'timnas', 'piala presiden']): 
        if w < 9.0: return False 
        return True

    return True

@lru_cache(maxsize=10000)
def is_match_akurat_v3(epg_name, epg_id, m3u_name):
    e = terjemahkan_nama(epg_name)
    m = terjemahkan_nama(m3u_name)

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
    
    if re.search(r'\b(spotv|bein|arena)\b', e_clean) and not REGEX_NUMBERS.search(e_clean): e_clean += ' 1'
    if re.search(r'\b(spotv|bein|arena)\b', m_clean) and not REGEX_NUMBERS.search(m_clean): m_clean += ' 1'

    e_k = REGEX_KUALITAS.sub('', e_clean).strip()
    m_k = REGEX_KUALITAS.sub('', m_clean).strip()

    e_num = REGEX_NUMBERS.findall(e_k)
    m_num = REGEX_NUMBERS.findall(m_k)
    en = e_num[0] if e_num else '0'
    mn = m_num[0] if m_num else '0'
    
    pengecualian_angka = ['badminton', 'arena', 'spotv']
    if not any(k in e_k for k in pengecualian_angka):
        if en != mn: return False

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
# V. FUNGSI SEDOT MULTITHREADING
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
# VI. PROSES EKSEKUSI UTAMA
# ==========================================
def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    match_data = {}
    epg_chans, epg_logos = {}, {}
    
    # ATURAN BARU: BATAS AKHIR HARI BESOK JAM 23:59:59 WIB (Super Ringan)
    besok = now_wib + timedelta(days=1)
    limit_date = besok.replace(hour=23, minute=59, second=59)

    load_mapping()

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

    print(f"Step 2: Memproses Data EPG (Hanya Sampai: {limit_date.strftime('%d-%m-%Y %H:%M')} WIB)...")
    for url in EPG_URLS:
        content = epg_contents.get(url)
        if not content: continue
        try:
            root = ET.fromstring(content)
            for ch in root.findall("channel"):
                cid, cn = ch.get("id"), ch.findtext("display-name")
                if cid and cn: 
                    cn_strip = cn.strip()
                    if not is_sports_channel(cn_strip): continue
                    
                    epg_chans[cid] = cn_strip
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

    print("Step 3: Menjahit M3U (Jalur EPG Normal & Jalur Tol Otomatis)...")
    keranjang_event_live = {} 
    up_tracker = set()
    
    for url in M3U_URLS:
        content = m3u_contents.get(url)
        if not content: continue
        
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
                
                if stream_url in GLOBAL_SEEN_STREAM_URLS:
                    block = []
                    continue
                GLOBAL_SEEN_STREAM_URLS.add(stream_url)
                
                extinf_idx = next((i for i, t in enumerate(block) if t.upper().startswith("#EXTINF")), -1)
                
                if extinf_idx != -1:
                    raw_extinf = block[extinf_idx]
                    
                    # FILTER SUPER CEPAT KHUSUS KPL203 (Abaikan VOD & Film!)
                    if "KPL203" in url:
                        if not re.search(r'(?i)group-title=["\'][^"\']*event', raw_extinf):
                            block = []
                            continue

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

                        # ==========================================
                        # 1. JALUR TOL UNIVERSAL (EVENT BERDASARKAN JAM)
                        # ==========================================
                        event_match = REGEX_EVENT.search(m3u_name)
                        if event_match:
                            hh, mm = int(event_match.group(1)), int(event_match.group(2))
                            
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
                                else: lbl = "" 
                                
                                judul = f"{flag} ⏳ {lbl}{jam} - {event_title} [Live Event]"
                                up_extinf = f'{clean_attr} group-title="📅 AKAN TAYANG" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                                
                                unique_link_up = f"{LINK_UPCOMING}?match={event_key}"
                                
                                if event_key not in keranjang_event_live: keranjang_event_live[event_key] = {}
                                keranjang_event_live[event_key]["UPCOMING"] = [{
                                    "order": 1, "sort": ev_start.timestamp(), "prioritas": 0, "data": [up_extinf, unique_link_up]
                                }]
                                
                            block = []
                            continue 

                        # ==========================================
                        # 2. JALUR NORMAL EPG (SPORTS & INDONESIA COMBINED)
                        # ==========================================
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
                                        
                                        m3u_display = re.sub(r'[\[\]\(\)]', '', m3u_name).strip()
                                        judul = f"{flag} 🔴 {jam} - {ev['title']} [{m3u_display}]"
                                        
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
                                        else: lbl = "" 
                                        
                                        m3u_display = re.sub(r'[\[\]\(\)]', '', m3u_name).strip()
                                        judul = f"{flag} ⏳ {lbl}{jam} - {ev['title']} [{m3u_display}]"
                                        
                                        up_extinf = f'{clean_attr} group-title="📅 AKAN TAYANG" tvg-id="{matched_cid}" tvg-logo="{final_logo}", {judul}'
                                        unique_link_up = f"{LINK_UPCOMING}?match={event_key}"
                                        
                                        if event_key not in keranjang_event_live: keranjang_event_live[event_key] = {}
                                        keranjang_event_live[event_key]["UPCOMING"] = [{
                                            "order": 1, "sort": ev['start'].timestamp(), "prioritas": 0, "data": [up_extinf, unique_link_up]
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
    
    m3u_header = f'#EXTM3U name="🔴 BAKUL WIFI SPORTS (Upd: {now_wib.strftime("%H:%M WIB")})"\n'
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_header)
        if not hasil_m3u: 
            f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA PERTANDINGAN\n{LINK_STANDBY}\n')
        for item in hasil_m3u: 
            f.write("\n".join(item["data"]) + "\n")

    print(f"Selesai! {len(hasil_m3u)} Jadwal (Fix beIN & Bebas Astro) Siap Meluncur.")

if __name__ == "__main__": main()
