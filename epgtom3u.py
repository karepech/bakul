import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import io

# ==========================================
# KONFIGURASI MULTI-EPG & M3U
# ==========================================
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",            
    "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml", 
    "https://epg.pw/api/epg.xml?channel_id=397400",                                         
    "https://epg.pw/xmltv/epg_lite.xml.gz"                                                  
]

M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
OUTPUT_FILE = "live_matches_only.m3u"

# ==========================================
# KONFIGURASI LINK VIDEO MANUAL
# ==========================================
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

# ==========================================
# DATABASE LOGO LIGA (PREMIUM LOOK)
# ==========================================
LOGO_DB = {
    "premier league": "https://upload.wikimedia.org/wikipedia/en/thumb/f/f2/Premier_League_Logo.svg/1200px-Premier_League_Logo.svg.png",
    "epl": "https://upload.wikimedia.org/wikipedia/en/thumb/f/f2/Premier_League_Logo.svg/1200px-Premier_League_Logo.svg.png",
    "serie a": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Serie_A_logo_2022.svg/1200px-Serie_A_logo_2022.svg.png",
    "laliga": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0f/LaLiga_logo_2023.svg/1200px-LaLiga_logo_2023.svg.png",
    "la liga": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0f/LaLiga_logo_2023.svg/1200px-LaLiga_logo_2023.svg.png",
    "bundesliga": "https://upload.wikimedia.org/wikipedia/en/thumb/d/df/Bundesliga_logo_%282017%29.svg/1200px-Bundesliga_logo_%282017%29.svg.png",
    "ligue 1": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Ligue1.svg/1200px-Ligue1.svg.png",
    "fa cup": "https://upload.wikimedia.org/wikipedia/en/thumb/b/b4/FA_Cup_logo.svg/1200px-FA_Cup_logo.svg.png",
    "champions league": "https://upload.wikimedia.org/wikipedia/en/thumb/b/bf/UEFA_Champions_League_logo_2.svg/1200px-UEFA_Champions_League_logo_2.svg.png",
    "europa league": "https://upload.wikimedia.org/wikipedia/en/thumb/f/f3/UEFA_Europa_League_logo_2021.svg/1200px-UEFA_Europa_League_logo_2021.svg.png",
    "nba": "https://upload.wikimedia.org/wikipedia/en/thumb/0/03/National_Basketball_Association_logo.svg/105px-National_Basketball_Association_logo.svg.png",
    "motogp": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/MotoGP_logo.svg/1200px-MotoGP_logo.svg.png",
    "f1": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/F1.svg/1200px-F1.svg.png",
    "formula 1": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/F1.svg/1200px-F1.svg.png",
    "badminton": "https://upload.wikimedia.org/wikipedia/en/thumb/a/a2/BWF_logo_2012.svg/1200px-BWF_logo_2012.svg.png",
    "bwf": "https://upload.wikimedia.org/wikipedia/en/thumb/a/a2/BWF_logo_2012.svg/1200px-BWF_logo_2012.svg.png",
    "default": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/87/Video_Camera_Icon.svg/1024px-Video_Camera_Icon.svg.png"
}

SPORT_KEYWORDS = ["sport", "bein", "spotv", "astro", "hub", "arena", "premier", "champions", "euro", "football", "soccer", "liga", "nba", "motogp", "badminton", "voli", "basket", "tennis", "f1", "ufc", "wwe"]
REPLAY_KEYWORDS = ["highlight", "replay", "classic", "best of", "re-run", "siaran ulang", "magazine", "preview", "review", "delay", "encore", "rpt", "repeat", "rewind", "recap", "recorded", "archives", "ulangan"]

def get_league_logo(title):
    t_lower = title.lower()
    for keyword, url in LOGO_DB.items():
        if keyword != "default" and keyword in t_lower:
            return url
    if ' vs ' in t_lower or ' v ' in t_lower:
        return LOGO_DB["default"]
    return LOGO_DB["default"]

def is_sport(text):
    if not text: return False
    return any(k in text.lower() for k in SPORT_KEYWORDS)

def is_fresh_live(prog, title, channel_name):
    if prog.find("previously-shown") is not None: return False
    if not title: return False
    t = title.lower()
    c = channel_name.lower()
    
    if any(k in t for k in REPLAY_KEYWORDS): return False
    if any(network in c for network in ['bein', 'spotv', 'astro', 'champions', 'premier', 'hub']):
        if 'vs' in t or ' v ' in t:
            if not re.search(r'\b(live|\(l\)|\[l\]|langsung)\b', t):
                return False 
    return True

def is_match_akurat(epg_name, m3u_name):
    if not epg_name or not m3u_name: return False
    epg_name = epg_name.lower().strip()
    m3u_name = m3u_name.lower().strip()

    hapus_kualitas = r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports)\b'
    epg_clean = re.sub(hapus_kualitas, '', epg_name)
    m3u_clean = re.sub(hapus_kualitas, '', m3u_name)

    num_epg_match = re.search(r'\d+', epg_clean)
    num_epg = num_epg_match.group() if num_epg_match else ""
    num_m3u_match = re.search(r'\d+', m3u_clean)
    num_m3u = num_m3u_match.group() if num_m3u_match else ""

    if num_epg != num_m3u: return False

    m3u_clean_text = re.sub(r'[^a-z0-9]', '', m3u_clean)
    epg_clean_text = re.sub(r'[^a-z0-9]', '', epg_clean)

    if epg_clean_text and m3u_clean_text:
        return epg_clean_text in m3u_clean_text or m3u_clean_text in epg_clean_text
    return False

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
    bersih = re.sub(r'(?i)\b(live|langsung|\(l\)|\[l\]|live on)\b', '', title)
    bersih = re.sub(r'\s+', ' ', bersih).strip()
    bersih = re.sub(r'^[\-\:\,\|]\s*', '', bersih)
    return bersih

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels = {}
    
    # Simpan jadwal per Channel ID
    jadwal_per_channel = {}

    # BATAS WAKTU: Menampilkan Jadwal Hingga Jam 06:00 Pagi Saja
    if now_wib.hour < 6:
        batas_waktu_upcoming = now_wib.replace(hour=6, minute=0, second=0, microsecond=0)
    else:
        batas_waktu_upcoming = (now_wib + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

    print("1. Mengunduh dan memproses daftar EPG...")
    for url in EPG_URLS:
        print(f" -> Memproses: {url.split('/')[-1].split('?')[0]} ...")
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
                if ch_id and ch_name and is_sport(ch_name):
                    if ch_id not in epg_channels:
                        epg_channels[ch_id] = ch_name.strip()
                    
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                    
                ch_name = epg_channels[ch_id]
                title_raw = prog.findtext("title") or ""
                
                if not is_fresh_live(prog, title_raw, ch_name): continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                if stop_dt <= now_wib: continue 
                
                # Buang jadwal yang tayangnya melewati jam 06:00 Pagi berikutnya
                if start_dt >= batas_waktu_upcoming: continue

                # Toleransi pindah ke LIVE 5 menit sebelum tayang
                waktu_toleransi_live = start_dt - timedelta(minutes=5)
                is_live = waktu_toleransi_live <= now_wib < stop_dt

                judul_bersih = bersihkan_judul_event(title_raw)
                logo_url = get_league_logo(title_raw)
                
                if ch_id not in jadwal_per_channel:
                    jadwal_per_channel[ch_id] = {}
                
                # Kunci unik per jadwal untuk mencegah duplikat EPG (tapi mengizinkan duplikat M3U/Backup)
                unik_epg_event = f"{start_dt.strftime('%Y%m%d%H%M')}_{judul_bersih.lower()}"
                
                if unik_epg_event not in jadwal_per_channel[ch_id]:
                    jadwal_per_channel[ch_id][unik_epg_event] = {
                        "title_display": judul_bersih,
                        "start_dt": start_dt,
                        "is_live": is_live,
                        "logo_url": logo_url
                    }
                else:
                    if is_live: # Prioritaskan status LIVE jika ada tumpang tindih EPG
                        jadwal_per_channel[ch_id][unik_epg_event]["is_live"] = True

        except Exception as e:
            continue

    print("\n2. Mengunduh M3U master Anda...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Meracik Playlist Event Premium (Mendukung Multi-Link Backup)...")
    hasil_akhir = []
    channel_block = []

    for line in m3u_lines:
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
                    _, nama_asli_m3u = extinf.split(",", 1)
                    nama_asli_m3u = nama_asli_m3u.strip()
                    
                    # Cari semua acara dari EPG yang tayang di channel M3U ini
                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u):
                            if ch_id in jadwal_per_channel:
                                
                                # Proses SEMUA acara yang ada di channel ini
                                for unik_key, event in jadwal_per_channel[ch_id].items():
                                    jam_str = event["start_dt"].strftime('%H:%M WIB')
                                    
                                    if event["is_live"]:
                                        grup_baru = "🔴 LIVE EVENT SPORTS"
                                        judul_akhir = f"🔴 {jam_str} {event['title_display']}"
                                        stream_final = stream_url # Pakai stream M3U asli karena sedang LIVE
                                        order = 0
                                    else:
                                        grup_baru = "📅 UPCOMING EVENT"
                                        judul_akhir = f"⏳ {jam_str} {event['title_display']}"
                                        stream_final = LINK_UPCOMING # Pakai link video MP4 5 menit Anda
                                        order = 1
                                        
                                    baris_extinf = f'#EXTINF:-1 group-title="{grup_baru}" tvg-logo="{event["logo_url"]}", {judul_akhir}'
                                    
                                    hasil_akhir.append({
                                        "kategori_order": order,
                                        "start_time": event["start_dt"].timestamp(),
                                        "title_sort": event['title_display'],
                                        "baris_lengkap": [baris_extinf, stream_final]
                                    })
                            break # Cukup ambil kecocokan channel pertama lalu lanjut ke link M3U berikutnya
            
            channel_block = []

    def sorting_logic(x):
        # 1. Pisahkan Folder LIVE dan UPCOMING
        # 2. Urutkan murni berdasarkan Jam Tayang
        # 3. Urutkan berdasarkan Nama Pertandingan
        return (x["kategori_order"], x["start_time"], x["title_sort"])

    print("4. Menyortir Berdasarkan Jam Tayang & Menyimpan File M3U Final...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write('#EXTM3U name="🔴 OLAHRAGA AKTIF"\n')
        
        if not hasil_akhir:
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA JADWAL\n')
            f.write(f'{LINK_STANDBY}\n')
        else:
            hasil_akhir.sort(key=sorting_logic)
            
            for item in hasil_akhir:
                for blk in item["baris_lengkap"]:
                    f.write(blk + "\n")

    print(f"\nSELESAI ✔ → {len(hasil_akhir)} link berhasil diracik (Termasuk link Backup!).")

if __name__ == "__main__":
    main()
