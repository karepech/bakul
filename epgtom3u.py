import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import io

# ==========================================
# KONFIGURASI MULTI-EPG & M3U (SUDAH DIPERBAIKI)
# ==========================================
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",            
    "https://warningfm.github.io/x1/epg/guide.xml.gz"                                                  
]

M3U_URLS = [
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u"
]

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

def get_flag(m3u_name):
    """Sistem Bendera Otomatis"""
    n = m3u_name.lower()
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'astro', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    
    if 'bein' in n and not any(x in n for x in [' en', ' hk', ' th', ' ph', ' my', ' sg', ' au']): 
        return "🇮🇩"
    if any(x in n for x in [' id', 'indo', 'vidio']): return "🇮🇩"
    
    return "📺" 

def is_allowed_sport(title, ch_name):
    """FILTER 1: PEMBANTAI ACARA SAMPAH & HURUF DEWA"""
    if not title: return False
    t = title.lower()
    c = ch_name.lower()
    
    # 1. HANCURKAN HURUF RUSIA/CINA/JEPANG/ARAB SECARA MUTLAK
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', title):
        return False

    # 2. DAFTAR HARAM: Buang Delay (D), Berita, Tenis, Tinju, Kriket, Basket, Senam, dll
    haram = [
        "(d)", "[d]", "delay", "replay", "re-run", "siaran ulang", "recorded", "archives",
        "news", "studio", "pre-match", "post-match", "update", "talk", "show", "weekly", 
        "magazine", "highlight", "classic", "review", "encore", "tba", 
        "fitness", "workout", "gym", "golden fit",
        "tennis", "wta", "atp", "wimbledon", "golf", "pga", "wwe", "ufc", "boxing", "fight", "mma", 
        "smackdown", "snooker", "darts", "rugby", "cricket", "icc", "mlb", "nhl", "nfl", "baseball", 
        "wbc", "basketball", "nba", "fiba", "movie", "special delivery", "billiard", "t20"
    ]
    if any(h in t for h in haram): return False

    # 3. PENGUNCI DOMAIN (BWF dilarang masuk channel Bola)
    bola_channels = ['arena bola', 'football', 'soccer', 'premier', 'laliga']
    if any(x in c for x in bola_channels):
        if any(x in t for x in ['badminton', 'bwf', 'motogp', 'f1', 'basket', 'tennis']):
            return False
    
    # 4. DAFTAR HALAL OLAHRAGA
    halal = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", "dutch", "eredivisie",
        "fc", "united", "city", "madrid", "barcelona", "chelsea", "arsenal", "liverpool", 
        "juventus", "milan", "inter", "bayern", "psg", "soccer", "football", "copa", "piala", 
        "afc", "aff", "fifa", "uefa", "mls", 
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", 
        "voli", "volley", "vnl", "proliga", "futsal", 
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint"
    ]
    
    # Loloskan jika ada di daftar Halal ATAU merupakan laga resmi (ada VS)
    if any(h in t for h in halal) or ' vs ' in t or ' v ' in t:
        return True
        
    return False

def is_match_akurat(epg_name, m3u_name):
    """FILTER 2: PENGUNCI KAMAR MUTLAK LEVEL DEWA (ANTI-NYASAR)"""
    if not epg_name or not m3u_name: return False
    e = epg_name.lower().strip()
    m = m3u_name.lower().strip()

    hapus_kualitas = r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|id|my|sg|network)\b'
    e_clean = re.sub(hapus_kualitas, '', e).strip()
    m_clean = re.sub(hapus_kualitas, '', m).strip()

    num_e = re.findall(r'\d+', e_clean)
    num_m = re.findall(r'\d+', m_clean)

    # Deteksi provider yang butuh proteksi ekstra ketat
    strict_nets = ['astro', 'bein', 'spotv', 'sportstars', 'soccer channel', 'fight']
    
    for net in strict_nets:
        if net in e_clean or net in m_clean:
            if (net in e_clean) != (net in m_clean): return False
            
            # Kunci Spesifik Astro
            if net == 'astro':
                subs = ['arena bola 2', 'arena bola', 'arena', 'supersport 1', 'supersport 2', 'supersport 3', 'supersport 4', 'supersport 5', 'supersport', 'cricket', 'badminton', 'football', 'golf', 'grandstand', 'premier']
                found_e = next((s for s in subs if s in e_clean), 'none')
                found_m = next((s for s in subs if s in m_clean), 'none')
                if found_e != found_m: return False
            
            # Kunci Spesifik beIN (Pisahkan xtra/extra)
            if net == 'bein':
                if ('xtra' in e_clean or 'extra' in e_clean) != ('xtra' in m_clean or 'extra' in m_clean): return False

            # Kunci Spesifik SpoTV
            if net == 'spotv':
                if ('now' in e_clean) != ('now' in m_clean): return False

            # Wajib sama angka (Jika tidak ada angka, dianggap channel 1)
            ne = num_e[0] if num_e else '1'
            nm = num_m[0] if num_m else '1'
            if ne != nm: return False
            
            return True

    # KUNCI UMUM (Cegah Bug String Kosong penyebab nyasar massal)
    e_alpha = re.sub(r'[^a-z0-9]', '', e_clean)
    m_alpha = re.sub(r'[^a-z0-9]', '', m_clean)
    if not e_alpha or not m_alpha: return False
    if len(e_alpha) < 3 or len(m_alpha) < 3: return e_alpha == m_alpha
    return e_alpha in m_alpha or m_alpha in e_alpha

def parse_epg_time(time_str):
    if not time_str: return None
    try:
        time_str = time_str.strip()
        if len(time_str) >= 20 and ('+' in time_str or '-' in time_str):
            dt = datetime.strptime(time_str[:20], "%Y%m%d%H%M%S %z")
            dt_wib = dt.astimezone(timezone(timedelta(hours=7)))
            return dt_wib.replace(tzinfo=None)
        else:
            dt = datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
            return dt + timedelta(hours=7)
    except Exception:
        return None

def bersihkan_judul_event(title):
    # Hapus embel-embel (L), (D), Live, agar judul rapi dan bersih
    bersih = re.sub(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\blive\b|\blangsung\b|\blive on\b)', '', title)
    bersih = re.sub(r'\s+', ' ', bersih).strip()
    bersih = re.sub(r'^[\-\:\,\|]\s*', '', bersih)
    return bersih

def is_valid_time(start_dt, title, ch_name):
    """FILTER 3: HUKUM WAKTU LIGA DUNIA (PEMBANTAI REPLAY PAGI/SIANG)"""
    waktu_float = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()
    c = ch_name.lower()

    bola_eropa = ['premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'la liga', 'laliga', 'uefa', 'europa', 'scottish', 'dutch', 'eredivisie']
    bola_amerika = ['mls', 'concacaf', 'libertadores', 'sudamericana', 'ncaa', 'liga mx', 'america']
    bola_asia = ['bri liga', 'liga 1', 'indonesia', 'afc', 'j-league', 'j1', 'k-league', 'asia', 'aff']

    is_eropa = any(k in t or k in c for k in bola_eropa)
    is_amerika = any(k in t or k in c for k in bola_amerika)
    is_asia = any(k in t or k in c for k in bola_asia)

    bola_umum = ['liga', 'fc', 'united', 'vs', 'v', 'soccer', 'football', 'bein']
    is_football = any(k in t or k in c for k in bola_umum)
    
    non_bola = ['badminton', 'bwf', 'motogp', 'f1', 'formula', 'voli', 'volleyball', 'futsal', 'moto2', 'moto3', 'sprint']
    is_non_bola = any(k in t for k in non_bola)

    # ATURAN KETAT WAKTU SEPAK BOLA
    if is_football and not is_non_bola:
        if is_eropa:
            if 5.0 <= waktu_float < 18.5: return False # Eropa Dilarang Tayang Jam 05:00 - 18:29 WIB
        elif is_asia:
            if 5.0 <= waktu_float < 15.0: return False # Asia Dilarang Tayang Jam 05:00 - 14:59 WIB
        elif is_amerika:
            pass # Amerika Bebas Tayang Pagi
        else:
            if 9.0 <= waktu_float < 15.0: return False # Bola yg gak jelas liganya, dilarang tayang jam 09:00 - 14:59 WIB

    return True

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels = {}
    jadwal_per_channel = {}

    # SIKLUS 24 JAM
    if now_wib.hour < 5:
        batas_waktu_upcoming = now_wib.replace(hour=5, minute=0, second=0, microsecond=0)
    else:
        batas_waktu_upcoming = (now_wib + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)

    print("1. Mengunduh dan memproses daftar EPG...")
    for url in EPG_URLS:
        try:
            r_epg = requests.get(url, timeout=120)
            if r_epg.status_code != 200: continue
                
            content = r_epg.content
            if content[:2] == b'\x1f\x8b':
                content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
                
            root = ET.fromstring(content)
            
            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                ch_name = ch.findtext("display-name")
                if ch_id and ch_name:
                    epg_channels[ch_id] = ch_name.strip()
                    
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                    
                ch_name = epg_channels[ch_id]
                title_raw = prog.findtext("title") or ""
                
                # Filter 1: Pembantai Sampah
                if not is_allowed_sport(title_raw, ch_name): continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                if stop_dt <= now_wib: continue 
                if start_dt >= batas_waktu_upcoming: continue

                # Filter 3: Hukum Waktu (Pembantai Replay Pagi/Siang)
                if not is_valid_time(start_dt, title_raw, ch_name):
                    continue

                # Filter 4: Durasi Sepak Bola Wajib >= 85 menit
                durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                if durasi_menit < 30: continue 

                bola_keywords = ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v']
                is_football = any(k in ch_name.lower() or k in title_raw.lower() for k in bola_keywords)
                non_bola = ['badminton', 'bwf', 'motogp', 'f1', 'formula', 'voli', 'volleyball', 'futsal', 'moto2', 'moto3', 'sprint']
                is_non_bola = any(k in title_raw.lower() for k in non_bola)

                if is_football and not is_non_bola:
                    if durasi_menit < 85: continue

                waktu_toleransi_live = start_dt - timedelta(minutes=5)
                is_live = waktu_toleransi_live <= now_wib < stop_dt

                judul_bersih = bersihkan_judul_event(title_raw)
                
                if ch_id not in jadwal_per_channel:
                    jadwal_per_channel[ch_id] = []
                
                jadwal_per_channel[ch_id].append({
                    "title_display": judul_bersih,
                    "start_dt": start_dt,
                    "stop_dt": stop_dt,
                    "is_live": is_live
                })

        except Exception as e:
            continue

    print("\n2. Menggabungkan file Multi M3U master Anda...")
    m3u_lines = []
    for url in M3U_URLS:
        print(f" -> Sedot M3U: {url.split('/')[-1]} ...")
        try:
            r_m3u = requests.get(url, timeout=30)
            r_m3u.raise_for_status()
            m3u_lines.extend(r_m3u.text.splitlines())
        except Exception as e:
            print(f"❌ Gagal menarik M3U dari {url}: {e}")
            continue

    if not m3u_lines:
        print("❌ Semua file M3U gagal diunduh. Script Berhenti.")
        return

    print("3. Meracik Playlist (Live: FULL BACKUP | Upcoming: MUTLAK 1 WAKIL)...")
    hasil_akhir = []
    channel_block = []
    
    # TRACKER PENGHEMAT BEBAN (HANYA UNTUK UPCOMING)
    upcoming_tracker_backup = set()
    upcoming_tracker_acara = set()

    for line in m3u_lines:
        baris = line.strip()
        if not baris: continue
        if baris.upper().startswith("#EXTM3U"): continue
