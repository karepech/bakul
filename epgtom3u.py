import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import concurrent.futures

# ==========================================
# I. KONFIGURASI LINK (EPG & M3U)
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
# II. LOGIKA PEMBLOKIRAN PINTU DEPAN (SUPER RINGAN)
# ==========================================

def is_sports_channel(name):
    """
    SATPAM PINTU DEPAN: Hanya TV yang mengandung kata ini yang boleh masuk.
    Saluran Religi & Berita otomatis ditendang!
    """
    n = name.lower()
    
    # 1. Daftar Hitam Mutlak (Membunuh saluran non-sport yang numpang nama)
    banned = ['oasis', 'hijrah', 'awani', 'ria', 'ceria', 'prima', 'warna', 'citra', 'arirang', 'cgtn', 'makkah', 'quran', 'alhijrah']
    if any(b in n for b in banned): return False
    
    # 2. Kata Kunci VIP (Astro dimasukkan agar tidak ada yang terpotong)
    sports_terms = [
        'sport', 'spo tv', 'spotv', 'bein', 'champions', 'arena', 
        'premier', 'golf', 'tennis', 'nba', 'nfl', 'supersport', 
        'grandstand', 'cricket', 'fight', 'espn', 'euro', 'fox', 
        'soccer', 'football', 'laliga', 'wwe', 'ufc', 'smackdown', 'hub',
        'mola', 'racing', 'moto', 'badminton', 'bwf', 'striker', 'astro'
    ]
    return any(term in n for term in sports_terms)

def is_allowed_sport_event(title):
    t = title.lower()
    haram = [
        "(d)", "[d]", "(r)", "[r]", "delay", "replay", "re-run", "siaran ulang", 
        "recorded", "archives", "tunda", "tayangan ulang", "rekap", "ulangan", 
        "rakaman", "cuplikan", "sorotan", "magazine", "highlight", "review", 
        "encore", "tba", "hl", "dl", "rev", "story", "dokumenter", "news", 
        "update", "jurnal", "talk", "show", "weekly", "kilas", "pre-match", 
        "build-up", "preview", "warm up", "classic", "rewind"
    ]
    if re.search(r'\b(?:' + '|'.join(haram) + r')\b', t): return False
    return True 

def is_valid_time(start_dt, title):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()

    if any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman']): return True
    if any(k in t for k in ['voli', 'volley', 'vnl', 'proliga']): return (12.0 <= w <= 20.0) or (w >= 22.0 or w <= 4.0) or (5.0 <= w <= 11.0)
    if any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula']): return (3.0 <= w <= 6.0) or (8.0 <= w <= 16.0) or (18.0 <= w <= 22.0)
    if any(k in t for k in ['premier league', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'champions league', 'arsenal', 'chelsea', 'madrid']): return w >= 18.0 or w <= 3.5
    if any(k in t for k in ['saudi', 'al nassr', 'al hilal']): return w >= 20.0 or w <= 3.0
    if any(k in t for k in ['liga 1', 'timnas', 'garuda', 'persib', 'persija', 'afc']): return 12.0 <= w <= 21.5
    return not (4.0 < w < 14.0)

# FUNGSI PENDUKUNG (Bendera & Pembersih Teks)
def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'astro', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'uk']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai']): return "🇹🇭"
    if any(x in n for x in [' au', 'aus']): return "🇦🇺"
    if 'bein' in n and not any(x in n for x in [' en', ' hk', ' th', ' ph', ' my', ' sg', ' au']): return "🇮🇩"
    if any(x in n for x in [' id', 'indo', 'vidio', 'rcti', 'sctv', 'mnc', 'tvri', 'antv']): return "🇮🇩"
    return "📺"

def bersihkan_judul_event(title):
    return re.sub(r'^[\-\:\,\|]\s*', '', re.sub(r'\s+', ' ', re.sub(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)', '', title))).strip()

def parse_epg_time(time_str):
    if not time_str: return None
    try:
        if len(time_str) >= 20: return datetime.strptime(time_str[:20], "%Y%m%d%H%M%S %z").astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return datetime.strptime(time_str[:14], "%Y%m%d%H%M%S") + timedelta(hours=7) 
    except: return None

def fetch_url(url):
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200: return url, r.content
    except: pass
    return url, None

# ==========================================
# III. PROSES EKSEKUSI (CEPAT & RINGAN)
# ==========================================

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels, epg_channel_logos, jadwal_per_channel = {}, {}, {}
    sumber_id_map = {url: str(idx + 1) for idx, url in enumerate(M3U_URLS)}
    batas_waktu_upcoming = (now_wib + timedelta(days=2)).replace(hour=5, minute=0, second=0, microsecond=0)

    print("Step 1: Download EPG (Hanya Membaca Kategori Olahraga)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_url, url): url for url in EPG_URLS if url}
        for future in concurrent.futures.as_completed(futures):
            url, content = future.result()
            if not content: continue
            try:
                if url.endswith(".gz") or content[:2] == b'\x1f\x8b': content = gzip.decompress(content)
                root = ET.fromstring(content)
                
                # SARING CHANNEL (Cuma Ambil TV Olahraga & Astro Aman)
                for ch in root.findall("channel"):
                    ch_id, ch_name = ch.get("id"), ch.findtext("display-name")
                    if ch_id and ch_name and is_sports_channel(ch_name):
                        epg_channels[ch_id] = ch_name.strip()
                        if ch.find("icon") is not None: epg_channel_logos[ch_id] = ch.find("icon").get("src", "").strip()
                
                # BACA JADWAL
                for prog in root.findall("programme"):
                    ch_id = prog.get("channel")
                    if ch_id not in epg_channels or prog.find("previously-shown") is not None: continue
                    title_raw = prog.findtext("title") or ""
                    
                    if not is_allowed_sport_event(title_raw): continue
                    start_dt, stop_dt = parse_epg_time(prog.get("start")), parse_epg_time(prog.get("stop"))
                    if not start_dt or not stop_dt or start_dt >= stop_dt or stop_dt <= now_wib or start_dt >= batas_waktu_upcoming: continue
                    if not is_valid_time(start_dt, title_raw): continue

                    durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                    if durasi_menit < 40: continue 

                    is_live = (start_dt - timedelta(minutes=5)) <= now_wib < stop_dt
                    if ch_id not in jadwal_per_channel: jadwal_per_channel[ch_id] = []
                    
                    jadwal_per_channel[ch_id].append({
                        "title_display": bersihkan_judul_event(title_raw),
                        "start_dt": start_dt, "stop_dt": stop_dt, "is_live": is_live,
                        "prog_logo": prog.find("icon").get("src") if prog.find("icon") is not None else ""
                    })
            except: pass

    print("Step 2: Download M3U Master...")
    m3u_lines_with_source = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_url, url): url for url in M3U_URLS if url}
        for future in concurrent.futures.as_completed(futures):
            url, content = future.result()
            if content:
                try:
                    for line in content.decode('utf-8').splitlines():
                        m3u_lines_with_source.append((sumber_id_map[url], line))
                except: pass

    print("Step 3: Meracik Playlist (Nama ikut EPG)...")
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
                    clean_m3u = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw|plus|max|sd|hq|ch|id|my|sg|network)\b', '', nama_asli_m3u.lower()).strip()
                    for ch_id, nama_epg in epg_channels.items():
                        clean_epg = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw|plus|max|sd|hq|ch|id|my|sg|network)\b', '', nama_epg.lower()).strip()
                        if clean_m3u in clean_epg or clean_epg in clean_m3u:
                            matched_epg_id = ch_id
                            break

                if matched_epg_id and matched_epg_id in jadwal_per_channel:
                    
                    # --- NAMA IKUT EPG (Sesuai Permintaan) ---
                    nama_channel_resmi = epg_channels[matched_epg_id]
                    
                    for event in jadwal_per_channel[matched_epg_id]:
                        jam_str = f"{event['start_dt'].strftime('%H:%M')}-{event['stop_dt'].strftime('%H:%M')} WIB"
                        logo_final = event["prog_logo"] or epg_channel_logos.get(matched_epg_id, "") or logo_asli
                        
                        # Menggunakan nama dari EPG, bukan dari M3U lagi!
                        judul_akhir = f"{bendera} {jam_str} - {event['title_display']} [{nama_channel_resmi}] ({id_sumber})"
                        kunci_pertandingan = f"{event['title_display']}_{event['start_dt'].timestamp()}"
                        
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
                            if kunci_pertandingan in upcoming_event_tracker:
                                continue
                            upcoming_event_tracker.add(kunci_pertandingan)
                            
                            grup_baru = "⏰ AKAN DATANG"
                            judul_final = judul_akhir.replace(bendera, f"{bendera} ⏰")
                            baris_extinf = f'#EXTINF:-1 tvg-id="{matched_epg_id}" tvg-logo="{logo_final}" group-title="{grup_baru}",{judul_final}\n{stream_url}'
                            upcoming_matches.append((event['start_dt'], baris_extinf))
                                    
            channel_block = []

    print("Step 4: MENGURUTKAN KRONOLOGIS (Sesuai Jam Tayang) & Menyimpan...")
    live_matches.sort(key=lambda x: x[0])       
    upcoming_matches.sort(key=lambda x: x[0])   

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for _, baris in live_matches: f.write(baris + "\n")
        for _, baris in upcoming_matches: f.write(baris + "\n")
            
    print(f"SELESAI! Playlist VIP Siap! ({len(live_matches)} Live, {len(upcoming_matches)} Akan Datang)")

if __name__ == "__main__":
    main()
