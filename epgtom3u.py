import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import io
import concurrent.futures
from difflib import SequenceMatcher

# ==========================================
# I. KONFIGURASI EMAS (MULTI-EPG & M3U VIP)
# ==========================================

EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"                   
]

RAW_MASTER_URLS = [
    "https://raw.githubusercontent.com/mimipipi22/lalajo/refs/heads/main/playlist25", 
    "https://semar25.short.gy", 
    "https://deccotech.online/tv/tvstream.html",
    "https://bit.ly/KPL203",
    "https://freeiptv2026.tsender57.workers.dev",
    "https://liveevent.iptvbonekoe.workers.dev",
    "http://sauridigital.my.id/kerbaunakal/2026TVGNS.html",
    "https://bit.ly/TVKITKAT",
    "https://spoo.me/tvplurl04",
    "https://aspaltvpasti.top/xxx/merah.php"
]
M3U_URLS = list(dict.fromkeys(RAW_MASTER_URLS))

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

# ==========================================
# OPTIMASI REGEX (LEBIH CEPAT & ANTI-JEBAKAN)
# ==========================================
REGEX_CHAMPIONS = re.compile(r'\b(?:champions?\s*tv|champions?|ctv)\s*(\d+)\b')
REGEX_STARS = re.compile(r'\bsports?\s+stars?\b')
REGEX_MNC = re.compile(r'\bmnc\s*sports?\b')
REGEX_SPO = re.compile(r'\bspo\s+tv\b')
REGEX_CYRILLIC_CJK = re.compile(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]')
REGEX_KUALITAS = re.compile(r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|id|my|sg|network)\b')
REGEX_NUMBERS = re.compile(r'\d+')
REGEX_WORDS = re.compile(r'[a-z0-9]+')
REGEX_JUDUL_1 = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_JUDUL_2 = re.compile(r'\s+')
REGEX_JUDUL_3 = re.compile(r'^[\-\:\,\|]\s*')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_VS = re.compile(r'\b(vs|v)\b')

# ==========================================
# II. FUNGSI PEMBANTU (FILTRASI & LOGIKA)
# ==========================================

def is_sports_channel(name):
    """ SATPAM PINTU DEPAN: Cegah saluran non-olahraga masuk! """
    n = name.lower()
    
    # GEMBOK 1: Daftar Hitam Dipertebal!
    banned = ['oasis', 'hijrah', 'awani', 'ria', 'ceria', 'prima', 'warna', 'citra', 
              'arirang', 'cgtn', 'makkah', 'quran', 'alhijrah', 'discovery', 'animal', 
              'history', 'news', 'kini', 'berita', 'rania', 'vod', 'cinema', 'movie', 
              'sinema', 'pelangi', 'bintang', 'entertainment']
    if any(b in n for b in banned): return False
    
    sports_terms = [
        'sport', 'spo tv', 'spotv', 'bein', 'champions', 'arena', 
        'premier', 'golf', 'tennis', 'nba', 'nfl', 'supersport', 
        'grandstand', 'cricket', 'fight', 'espn', 'euro', 'fox', 
        'soccer', 'football', 'laliga', 'wwe', 'ufc', 'smackdown', 'hub',
        'mola', 'racing', 'moto', 'badminton', 'bwf', 'striker', 'astro'
    ]
    return any(term in n for term in sports_terms)

def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'astro', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    if 'bein' in n and not any(x in n for x in [' en', ' hk', ' th', ' ph', ' my', ' sg', ' au']): return "🇮🇩"
    if any(x in n for x in [' id', 'indo', 'vidio', 'rcti', 'sctv', 'mnc', 'tvri', 'antv', 'indosiar', 'rtv', 'inews']): return "🇮🇩"
    return "📺" 

def get_region_code(text):
    t = text.lower()
    if re.search(r'\b(au|aus|australia|optus)\b', t): return 'AU'
    if re.search(r'\b(hk|hong\s*kong)\b', t): return 'HK'
    if re.search(r'\b(th|thai|thailand)\b', t): return 'TH'
    if re.search(r'\b(my|malaysia|astro)\b', t): return 'MY'
    if re.search(r'\b(sg|singapore|starhub)\b', t): return 'SG'
    if re.search(r'\b(ph|philippines)\b', t): return 'PH'
    if re.search(r'\b(arab|mena|ae|middle\s*east)\b', t): return 'ARAB'
    if re.search(r'\b(uk|english|en)\b', t): return 'UK'
    if re.search(r'\b(us|usa)\b', t): return 'US'
    if re.search(r'\b(id|indo|indonesia)\b', t): return 'ID'
    return 'UNKNOWN'

def normalisasi_alias(name):
    n = name.lower().strip()
    n = REGEX_CHAMPIONS.sub(r'champions tv \1', n)
    n = REGEX_STARS.sub('sportstars', n) 
    n = REGEX_MNC.sub('sportstars', n)    
    n = REGEX_SPO.sub('spotv', n)              
    return n

def is_allowed_sport_event(title, ch_name):
    t = title.lower().strip()
    c = ch_name.lower().strip()
    
    # GEMBOK 2: Anti-Filler (Jika Judul Acara = Nama Channel, berarti jadwal kosong!)
    if t == c or len(t) < 4: 
        return False

    haram = [
        "(d)", "[d]", "(r)", "[r]", "delay", "replay", "re-run", "siaran ulang", "recorded", "archives", 
        "tunda", "tayangan ulang", "rekap", "ulangan", "rakaman", "cuplikan", "sorotan", "best of", "planet",
        "news", "studio", "update", "talk", "show", "weekly", "kilas", "jurnal", "pre-match", "build-up", "build up",
        "preview", "road to", "kick-off show", "warm up", "menuju kick off", "classic", "rewind", "makkah", "quran", "religi",
        "magazine", "highlight", "review", "encore", "tba", "hl", "dl", "rev", "story", "dokumenter"
    ]
    if re.search(r'\b(?:' + '|'.join(haram) + r')\b', t): return False
    return True

def kemiripan_teks(a, b):
    return SequenceMatcher(None, a, b).ratio()

def is_match_akurat(epg_name, m3u_name, epg_id="", m3u_tvg_id=""):
    if epg_id and m3u_tvg_id:
        if epg_id.lower() == m3u_tvg_id.lower(): return True

    if not epg_name or not m3u_name: return False
    
    reg_epg = get_region_code(epg_name + " " + epg_id)
    reg_m3u = get_region_code(m3u_name)
    if reg_epg == 'UNKNOWN' and any(net in epg_name.lower() for net in ['bein', 'spotv', 'eurosport', 'fox']): reg_epg = 'ID' 
    if reg_epg != 'UNKNOWN' and reg_m3u != 'UNKNOWN' and reg_epg != reg_m3u: return False

    e_clean = REGEX_KUALITAS.sub('', normalisasi_alias(epg_name)).strip()
    m_clean = REGEX_KUALITAS.sub('', normalisasi_alias(m3u_name)).strip()
    
    num_e = REGEX_NUMBERS.findall(e_clean)
    num_m = REGEX_NUMBERS.findall(m_clean)
    if num_e != num_m: return False

    strict_nets = ['astro', 'bein', 'spotv', 'sportstars', 'soccer channel', 'fight', 'champions', 'hub', 'antv', 'rcti', 'sctv', 'indosiar']
    for net in strict_nets:
        if net in e_clean or net in m_clean:
            if (net in e_clean) != (net in m_clean): return False

    if kemiripan_teks(e_clean, m_clean) >= 0.85: return True

    e_words = set(REGEX_WORDS.findall(e_clean))
    m_words = set(REGEX_WORDS.findall(m_clean))
    if e_words and m_words:
        if e_words.issubset(m_words) or m_words.issubset(e_words): return True
    return False

def parse_epg_time(time_str):
    if not time_str: return None
    try:
        if len(time_str) >= 20 and ('+' in time_str or '-' in time_str):
            dt = datetime.strptime(time_str[:20], "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        else:
            return datetime.strptime(time_str[:14], "%Y%m%d%H%M%S") + timedelta(hours=7) 
    except Exception:
        return None

def bersihkan_judul_event(title):
    bersih = REGEX_JUDUL_1.sub('', title)
    bersih = REGEX_JUDUL_2.sub(' ', bersih).strip()
    return REGEX_JUDUL_3.sub('', bersih)

# ==========================================================
# FILTER WAKTU SUPER PRESISI (HUKUM JAM MULAI KICK-OFF)
# ==========================================================
def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0) 
    t = title.lower()

    if any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'swiss open', 'china open', 'china masters', 'macau open']): return True
    if any(k in t for k in ['voli', 'volley', 'vnl', 'proliga']): return (12.0 <= w <= 20.0) or (w >= 22.0 or w <= 4.0) or (5.0 <= w <= 11.0)
    if any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula', 'grand prix', 'sprint']): return (3.0 <= w <= 6.0) or (8.0 <= w <= 16.0) or (18.0 <= w <= 22.0)
    
    eropa = ['premier league', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'eredivisie', 'uefa', 'ucl', 'champions league', 'euro ', 'carabao', 'copa del rey', 'english championship', 'dfb', 'manchester united', 'manchester city', 'arsenal', 'chelsea', 'liverpool', 'tottenham', 'real madrid', 'barcelona', 'atletico', 'bayern', 'dortmund', 'juventus', 'inter milan', 'ac milan', 'napoli', 'psg']
    if any(k in t for k in eropa): return w >= 18.0 or w <= 3.5
    
    afrika_saudi = ['saudi', 'roshn', 'al nassr', 'al hilal', 'caf ', 'africa', 'afcon']
    if any(k in t for k in afrika_saudi): return w >= 20.0 or w <= 3.0
    
    australia = ['a-league', 'a league', 'nrl', 'afl', 'melbourne', 'sydney']
    if any(k in t for k in australia): return 8.0 <= w <= 17.0
    
    asia_indo = ['j-league', 'j1', 'j2', 'j3', 'k-league', 'k league', 'afc', 'asian cup', 'aff', 'liga 1', 'bri liga', 'shopee', 'piala presiden', 'liga 2', 'nusantara', 'timnas', 'garuda', 'persib', 'persija', 'persebaya']
    if any(k in t for k in asia_indo): return 12.0 <= w <= 21.5
    
    amerika = ['mls', 'major league soccer', 'concacaf', 'libertadores', 'sudamericana', 'liga mx', 'usl', 'argentina', 'brasil', 'brasileiro', 'campeonato', 'copa america', 'nba', 'nfl', 'inter miami', 'la galaxy']
    if any(k in t for k in amerika): return 2.0 <= w <= 11.5

    return not (4.0 < w < 14.0)

def fetch_url(url):
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200: return url, r.content
    except: pass
    return url, None

# ==========================================
# III. MAIN EKSEKUSI (INTI SCRIPT)
# ==========================================

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels, epg_channel_logos, jadwal_per_channel = {}, {}, {}

    print("\n=============================================")
    print("📡 DAFTAR ID SUMBER M3U (AUDIT LINK)")
    print("=============================================")
    sumber_id_map = {}
    for idx, url in enumerate(M3U_URLS):
        id_sumber = str(idx + 1)
        sumber_id_map[url] = id_sumber
        print(f"[{id_sumber}] -> {url.split('/')[-1] if 'bit.ly' not in url else url}")
    print("=============================================\n")

    batas_waktu_upcoming = (now_wib + timedelta(days=2)).replace(hour=5, minute=0, second=0, microsecond=0)

    print(f"Step 1: Download {len(EPG_URLS)} EPG Inti (Hanya Kategori Olahraga)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_url, url): url for url in EPG_URLS if url}
        for future in concurrent.futures.as_completed(futures):
            url, content = future.result()
            if not content: continue
            
            try:
                if url.endswith(".gz") or content[:2] == b'\x1f\x8b': content = gzip.decompress(content)
                root = ET.fromstring(content)
                
                for ch in root.findall("channel"):
                    ch_id, ch_name = ch.get("id"), ch.findtext("display-name")
                    if ch_id and ch_name and is_sports_channel(ch_name):
                        epg_channels[ch_id] = ch_name.strip()
                        if ch.find("icon") is not None: epg_channel_logos[ch_id] = ch.find("icon").get("src", "").strip()
                        
                for prog in root.findall("programme"):
                    ch_id = prog.get("channel")
                    if ch_id not in epg_channels or prog.find("previously-shown") is not None: continue

                    title_raw = prog.findtext("title") or ""
                    desc_raw = prog.findtext("desc") or ""
                    ch_name = epg_channels[ch_id]
                    
                    is_tag_live = (prog.find("live") is not None) or (prog.find("new") is not None)
                    
                    if not is_allowed_sport_event(title_raw + " " + desc_raw, ch_name): continue
                        
                    start_dt, stop_dt = parse_epg_time(prog.get("start")), parse_epg_time(prog.get("stop"))
                    if not start_dt or not stop_dt or start_dt >= stop_dt or stop_dt <= now_wib or start_dt >= batas_waktu_upcoming: continue
                    
                    if not is_tag_live:
                        if not is_valid_time(start_dt, title_raw, ch_name): continue

                    durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                    if durasi_menit < 30: continue 

                    is_football = any(k in ch_name.lower() or k in title_raw.lower() for k in ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v'])
                    if is_football and durasi_menit < 85: continue

                    is_live = (start_dt - timedelta(minutes=5)) <= now_wib < stop_dt
                    
                    if ch_id not in jadwal_per_channel: jadwal_per_channel[ch_id] = []
                    
                    jadwal_per_channel[ch_id].append({
                        "title_display": bersihkan_judul_event(title_raw),
                        "start_dt": start_dt, "stop_dt": stop_dt, "is_live": is_live,
                        "prog_logo": prog.find("icon").get("src") if prog.find("icon") is not None else ""
                    })
            except Exception: pass

    print(f"Step 2: Download {len(M3U_URLS)} File M3U Master...")
    m3u_lines_with_source = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_url, url): url for url in M3U_URLS if url}
        for future in concurrent.futures.as_completed(futures):
            url, content = future.result()
            if content:
                try:
                    lines = content.decode('utf-8').splitlines()
                    for line in lines: m3u_lines_with_source.append((sumber_id_map[url], line))
                except: pass

    print("Step 3: Meracik Playlist (Urutan Waktu & Smart Tracker)...")
    live_matches, upcoming_matches = [], []
    channel_block = []
    
    upcoming_event_tracker = set() 
    live_url_tracker = set()       
    provider_live_tracker = set()  

    for id_sumber, line in m3u_lines_with_source:
        baris = line.strip()
        if not baris or baris.upper().startswith("#EXTM3U"): continue
        if baris.startswith("#"):
            channel_block.append(baris)
        else:
            stream_url = baris
            extinf = next((tag for tag in channel_block if tag.upper().startswith("#EXTINF")), None)
            
            if extinf and "," in extinf:
                bagian_atribut, nama_asli_m3u = extinf.split(",", 1)
                nama_asli_m3u = nama_asli_m3u.strip()
                
                if not is_sports_channel(nama_asli_m3u):
                    channel_block = []
                    continue

                tvg_id_asli = re.search(r'(?i)tvg-id=(["\'])(.*?)\1', bagian_atribut)
                tvg_id_asli = tvg_id_asli.group(2) if tvg_id_asli else ""
                logo_asli = re.search(r'(?i)tvg-logo=(["\'])(.*?)\1', bagian_atribut)
                logo_asli = logo_asli.group(2) if logo_asli else ""
                bendera = get_flag(nama_asli_m3u)

                matched_epg_id = None
                if tvg_id_asli and tvg_id_asli in epg_channels:
                    matched_epg_id = tvg_id_asli
                else:
                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u, ch_id, tvg_id_asli):
                            matched_epg_id = ch_id
                            break

                if matched_epg_id and matched_epg_id in jadwal_per_channel:
                    nama_channel_resmi = epg_channels[matched_epg_id]
                    
                    for event in jadwal_per_channel[matched_epg_id]:
                        jam_str = f"{event['start_dt'].strftime('%H:%M')}-{event['stop_dt'].strftime('%H:%M')} WIB"
                        logo_final = event["prog_logo"] or epg_channel_logos.get(matched_epg_id, "") or logo_asli
                        
                        judul_akhir = f"{bendera} {jam_str} - {event['title_display']} [{nama_channel_resmi}] ({id_sumber})"
                        
                        # GEMBOK 3: Smart Tracker (Hanya baca jam + 8 huruf awal judul untuk deteksi duplikat)
                        clean_title_for_key = REGEX_NON_ALPHANUM.sub('', event['title_display'].lower())[:8]
                        kunci_pertandingan_pintar = f"{clean_title_for_key}_{event['start_dt'].timestamp()}"
                        
                        if event["is_live"]:
                            kunci_internal = f"{id_sumber}_{matched_epg_id}_{event['start_dt'].timestamp()}"
                            if stream_url in live_url_tracker or kunci_internal in provider_live_tracker:
                                continue 
                            live_url_tracker.add(stream_url)
                            provider_live_tracker.add(kunci_internal)
                            
                            grup_baru = "🔴 ACARA SEDANG TAYANG"
                            judul_final = judul_akhir.replace(bendera, f"{bendera} 🔴")
                            baris_extinf = f'#EXTINF:-1 tvg-id="{matched_epg_id}" tvg-logo="{logo_final}" group-title="{grup_baru}",{judul_final}\n{stream_url}'
                            live_matches.append((event['start_dt'], baris_extinf))
                            
                        else:
                            if kunci_pertandingan_pintar in upcoming_event_tracker:
                                continue
                            upcoming_event_tracker.add(kunci_pertandingan_pintar)
                            
                            grup_baru = "⏰ AKAN DATANG"
                            judul_final = judul_akhir.replace(bendera, f"{bendera} ⏰")
                            baris_extinf = f'#EXTINF:-1 tvg-id="{matched_epg_id}" tvg-logo="{logo_final}" group-title="{grup_baru}",{judul_final}\n{stream_url}'
                            upcoming_matches.append((event['start_dt'], baris_extinf))
                                    
            channel_block = []

    print(f"Step 4: MENGURUTKAN KRONOLOGIS & Menyimpan ke {OUTPUT_FILE}...")
    live_matches.sort(key=lambda x: x[0])       
    upcoming_matches.sort(key=lambda x: x[0])   

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for _, baris in live_matches: f.write(baris + "\n")
        for _, baris in upcoming_matches: f.write(baris + "\n")
            
    print(f"SELESAI! Playlist Rapi Siap Pakai! ({len(live_matches)} Live, {len(upcoming_matches)} Akan Datang)")

if __name__ == "__main__":
    main()
