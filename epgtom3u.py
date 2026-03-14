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
    "https://raw.githubusercontent.com/mimipipi22/lalajo/refs/heads/main/playlist25", # (1)
    "https://semar25.short.gy",                                                       # (2)
    "https://deccotech.online/tv/tvstream.html",                                      # (3)
    "https://bit.ly/KPL203",                                                          # (4)
    "https://freeiptv2026.tsender57.workers.dev",                                     # (5)
    "https://liveevent.iptvbonekoe.workers.dev",                                      # (6)
    "http://sauridigital.my.id/kerbaunakal/2026TVGNS.html",                           # (7)
    "https://bit.ly/TVKITKAT",                                                        # (8)
    "https://spoo.me/tvplurl04",                                                      # (9)
    "https://aspaltvpasti.top/xxx/merah.php"                                          # (10)
]
M3U_URLS = list(dict.fromkeys(RAW_MASTER_URLS))

OUTPUT_FILE = "live_matches_only.m3u"

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

def normalisasi_alias(name):
    n = name.lower().strip()
    n = REGEX_CHAMPIONS.sub(r'champions tv \1', n)
    n = REGEX_STARS.sub('sportstars', n) 
    n = REGEX_MNC.sub('sportstars', n)    
    n = REGEX_SPO.sub('spotv', n)              
    return n

def is_allowed_sport(title, ch_name):
    if not title: return False
    t = title.lower()
    c = normalisasi_alias(ch_name)
    
    if REGEX_CYRILLIC_CJK.search(t): return False

    if 'astro' in c:
        astro_haram = ['awani', 'ria', 'oasis', 'prima', 'rania', 'citra', 'hijrah', 'ceria', 'warna', 'vellithirai', 'vinmeen', 'shiq', 'kulliyyah']
        if any(x in c for x in astro_haram): return False

    haram = [
        "(d)", "[d]", "(r)", "[r]", "delay", "replay", "re-run", "siaran ulang", "recorded", "archives", 
        "tunda", "tayangan ulang", "rekap", "ulangan", "rakaman", "cuplikan", "sorotan", "best of", "planet",
        "news", "studio", "update", "talk", "show", "weekly", "kilas", "jurnal", "pre-match", "build-up", "build up",
        "preview", "road to", "kick-off show", "warm up", "menuju kick off", "classic", "rewind", "makkah", "quran", "religi",
        "magazine", "highlight", "review", "encore", "tba", "hl", "dl", "rev", "story", "dokumenter",
        "fitness", "workout", "gym", "golden fit", "masterchef", "apa kabar", "lfctv", "mutv", "chelsea tv",
        "tennis", "wta", "atp", "wimbledon", "golf", "pga", "wwe", "ufc", "boxing", "fight", "mma", 
        "smackdown", "snooker", "darts", "rugby", "cricket", "icc", "mlb", "nhl", "baseball", 
        "wbc", "basketball", "fiba", "movie", "special delivery", "billiard", "t20", "cleaning", "maniac", "brian"
    ]
    if re.search(r'\b(?:' + '|'.join(haram) + r')\b', t): return False

    bola_channels = ['arena bola', 'football', 'soccer', 'premier', 'laliga']
    if any(x in c for x in bola_channels):
        if any(x in t for x in ['badminton', 'bwf', 'motogp', 'f1', 'basket', 'tennis']): return False
    
    halal = [
        "live", "langsung",
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", "dutch", "eredivisie",
        "manchester city", "manchester united", "madrid", "barcelona", "chelsea", "arsenal", "liverpool", "juventus", "milan", "inter", "bayern", "psg", 
        "bri liga 1", "timnas", "garuda", "sea games", "asean games", "soccer", "football", "copa", "piala", "fifa", "uefa", "mls", "afc", "aff",
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", "yonex", "swiss open", "china open", "china masters", "macau open", "indonesia masters",
        "voli", "volley", "vnl", "proliga", "futsal",
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint", "nba", "nfl"
    ]
    
    if re.search(r'\b(?:' + '|'.join(halal).replace('+', r'\+') + r')\b', t) or REGEX_VS.search(t):
        return True
    return False

def kemiripan_teks(a, b):
    return SequenceMatcher(None, a, b).ratio()

def is_match_akurat(epg_name, m3u_name, epg_id="", m3u_tvg_id=""):
    if epg_id and m3u_tvg_id:
        if epg_id.lower() == m3u_tvg_id.lower():
            return True

    if not epg_name or not m3u_name: return False
    e_clean = REGEX_KUALITAS.sub('', normalisasi_alias(epg_name)).strip()
    m_clean = REGEX_KUALITAS.sub('', normalisasi_alias(m3u_name)).strip()
    
    num_e = REGEX_NUMBERS.findall(e_clean)
    num_m = REGEX_NUMBERS.findall(m_clean)
    if num_e != num_m: return False

    strict_nets = ['astro', 'bein', 'spotv', 'sportstars', 'soccer channel', 'fight', 'champions', 'hub']
    for net in strict_nets:
        if net in e_clean or net in m_clean:
            if (net in e_clean) != (net in m_clean): return False

    if kemiripan_teks(e_clean, m_clean) >= 0.85:
        return True

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

def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()

    if any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'swiss open', 'china open', 'china masters', 'macau open']): 
        return True
    if any(k in t for k in ['voli', 'volley', 'vnl', 'proliga']):
        if (12.0 <= w <= 20.0) or (w >= 22.0 or w <= 4.0) or (5.0 <= w <= 11.0): return True
        return False
    if any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula', 'grand prix', 'sprint']):
        if (3.0 <= w <= 6.0) or (8.0 <= w <= 16.0) or (18.0 <= w <= 22.0): return True
        return False

    eropa = ['premier league', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'eredivisie', 'uefa', 'ucl', 'champions league', 'euro ', 'carabao', 'copa del rey', 'english championship', 'dfb', 'manchester united', 'manchester city', 'arsenal', 'chelsea', 'liverpool', 'tottenham', 'real madrid', 'barcelona', 'atletico', 'bayern', 'dortmund', 'juventus', 'inter milan', 'ac milan', 'napoli', 'psg']
    if any(k in t for k in eropa):
        if w >= 18.0 or w <= 3.5: return True
        return False 

    afrika_saudi = ['saudi', 'roshn', 'al nassr', 'al hilal', 'caf ', 'africa', 'afcon']
    if any(k in t for k in afrika_saudi):
        if w >= 20.0 or w <= 3.0: return True
        return False

    australia = ['a-league', 'a league', 'nrl', 'afl', 'melbourne', 'sydney']
    if any(k in t for k in australia):
        if 8.0 <= w <= 17.0: return True
        return False

    asia_indo = ['j-league', 'j1', 'j2', 'j3', 'k-league', 'k league', 'afc', 'asian cup', 'aff', 'liga 1', 'bri liga', 'shopee', 'piala presiden', 'liga 2', 'nusantara', 'timnas', 'garuda', 'persib', 'persija', 'persebaya']
    if any(k in t for k in asia_indo):
        if 12.0 <= w <= 21.5: return True
        return False 

    amerika = ['mls', 'major league soccer', 'concacaf', 'libertadores', 'sudamericana', 'liga mx', 'usl', 'argentina', 'brasil', 'brasileiro', 'campeonato', 'copa america', 'nba', 'nfl', 'inter miami', 'la galaxy']
    if any(k in t for k in amerika):
        if 2.0 <= w <= 11.5: return True
        return False 

    if 4.0 < w < 14.0: 
        return False
    return True

def fetch_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, timeout=30, headers=headers)
        if r.status_code == 200:
            return url, r.content
    except Exception:
        pass
    return url, None

# ==========================================
# III. MAIN EKSEKUSI (INTI SCRIPT)
# ==========================================

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels = {}
    epg_channel_logos = {} 
    jadwal_per_channel = {}

    # MEMBUAT KAMUS ID SUMBER LINK MASTER
    print("\n=============================================")
    print("📡 DAFTAR ID SUMBER M3U (LEGEND)")
    print("=============================================")
    sumber_id_map = {}
    for idx, url in enumerate(M3U_URLS):
        id_sumber = str(idx + 1)
        sumber_id_map[url] = id_sumber
        print(f"[{id_sumber}] -> {url.split('/')[-1] if 'bit.ly' not in url else url}")
    print("=============================================\n")

    if now_wib.hour < 5:
        batas_waktu_upcoming = (now_wib + timedelta(days=2)).replace(hour=5, minute=0, second=0, microsecond=0)
    else:
        batas_waktu_upcoming = (now_wib + timedelta(days=3)).replace(hour=5, minute=0, second=0, microsecond=0)

    print(f"Step 1: Mengunduh {len(EPG_URLS)} EPG Inti secara bersamaan...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_url, url): url for url in EPG_URLS if url}
        for future in concurrent.futures.as_completed(futures):
            url, content = future.result()
            if not content: continue
            
            try:
                if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                    content = gzip.decompress(content)
                root = ET.fromstring(content)
                
                for ch in root.findall("channel"):
                    ch_id = ch.get("id")
                    ch_name = ch.findtext("display-name")
                    icon_node = ch.find("icon")
                    if ch_id and ch_name:
                        epg_channels[ch_id] = ch_name.strip()
                        if icon_node is not None and icon_node.get("src"):
                            epg_channel_logos[ch_id] = icon_node.get("src").strip()
                            
                for prog in root.findall("programme"):
                    ch_id = prog.get("channel")
                    if ch_id not in epg_channels: continue
                    if prog.find("previously-shown") is not None: continue

                    title_raw = prog.findtext("title") or ""
                    ch_name = epg_channels[ch_id]
                    if not is_allowed_sport(title_raw, ch_name): continue
                        
                    start_dt = parse_epg_time(prog.get("start"))
                    stop_dt = parse_epg_time(prog.get("stop"))
                    if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                    if stop_dt <= now_wib: continue 
                    if start_dt >= batas_waktu_upcoming: continue
                    if not is_valid_time(start_dt, title_raw, ch_name): continue

                    durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                    if durasi_menit < 30: continue 

                    is_football = any(k in ch_name.lower() or k in title_raw.lower() for k in ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v'])
                    if is_football and durasi_menit < 85: continue

                    waktu_toleransi_live = start_dt - timedelta(minutes=5)
                    is_live = waktu_toleransi_live <= now_wib < stop_dt

                    if ch_id not in jadwal_per_channel:
                        jadwal_per_channel[ch_id] = []
                    
                    jadwal_per_channel[ch_id].append({
                        "title_display": bersihkan_judul_event(title_raw),
                        "start_dt": start_dt,
                        "stop_dt": stop_dt,
                        "is_live": is_live,
                        "prog_logo": prog.find("icon").get("src") if prog.find("icon") is not None else ""
                    })
            except Exception:
                pass

    print(f"Step 2: Mengunduh {len(M3U_URLS)} File M3U Master secara bersamaan...")
    # Menyimpan baris M3U beserta ID Sumbernya
    m3u_lines_with_source = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_url, url): url for url in M3U_URLS if url}
        for future in concurrent.futures.as_completed(futures):
            url, content = future.result()
            if content:
                try:
                    id_sumber = sumber_id_map[url]
                    lines = content.decode('utf-8').splitlines()
                    for line in lines:
                        # Kita pasangkan setiap baris dengan ID sumbernya
                        m3u_lines_with_source.append((id_sumber, line))
                except: pass

    print("Step 3: Meracik Playlist VIP Olahraga Aktif...")
    hasil_akhir = []
    channel_block = []
    live_stream_tracker = set()

    for id_sumber, line in m3u_lines_with_source:
        baris = line.strip()
        if not baris: continue
        if baris.upper().startswith("#EXTM3U"): continue

        if baris.startswith("#"):
            channel_block.append(baris)
        else:
            stream_url = baris
            extinf_idx = -1
            
            for i, tag in enumerate(channel_block):
                if tag.upper().startswith("#EXTINF"):
                    extinf_idx = i
                    break
            
            if extinf_idx != -1:
                extinf = channel_block[extinf_idx]
                if "," in extinf:
                    bagian_atribut, nama_asli_m3u = extinf.split(",", 1)
                    nama_asli_m3u = nama_asli_m3u.strip()
                    
                    logo_asli_match = re.search(r'(?i)tvg-logo=(["\'])(.*?)\1', bagian_atribut)
                    logo_asli = logo_asli_match.group(2) if logo_asli_match else ""

                    tvg_id_match = re.search(r'(?i)tvg-id=(["\'])(.*?)\1', bagian_atribut)
                    tvg_id_asli = tvg_id_match.group(2) if tvg_id_match else ""
                    
                    bendera = get_flag(nama_asli_m3u)

                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u, ch_id, tvg_id_asli):
                            if ch_id in jadwal_per_channel:
                                for event in jadwal_per_channel[ch_id]:
                                    jam_mulai = event["start_dt"].strftime('%H:%M')
                                    jam_selesai = event["stop_dt"].strftime('%H:%M')
                                    jam_str = f"{jam_mulai}-{jam_selesai} WIB"
                                    
                                    logo_final = event["prog_logo"] or epg_channel_logos.get(ch_id, "") or logo_asli
                                    
                                    if event["is_live"]:
                                        kunci_live = f"{ch_id}_{event['start_dt'].timestamp()}_{stream_url}"
                                        if kunci_live in live_stream_tracker:
                                            continue 
                                        live_stream_tracker.add(kunci_live)
                                        
                                        grup_baru = "🔴 ACARA SEDANG TAYANG"
                                        
                                        # === PENAMBAHAN ID SUMBER DI SINI ===
                                        # Contoh output: 🇮🇩 🔴 19:00-21:00 WIB - Timnas vs Jepang [beIN 1] (1)
                                        judul_akhir = f"{bendera} 🔴 {jam_str} - {event['title_display']} [{nama_asli_m3u}] ({id_sumber})"
                                        
                                        baris_extinf = f'#EXTINF:-1 tvg-id="{ch_id}" tvg-logo="{logo_final}" group-title="{grup_baru}",{judul_akhir}\n{stream_url}'
                                        hasil_akhir.append(baris_extinf)
                                        
            # Bersihkan blok setelah URL video ditemukan
            channel_block = []

    print(f"Step 4: Menyimpan {len(hasil_akhir)} pertandingan live ke dalam {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for saluran in sorted(hasil_akhir):
            f.write(saluran + "\n")
            
    print("Selesai! Playlist M3U VIP Anda berhasil dibuat.")

if __name__ == "__main__":
    main()
