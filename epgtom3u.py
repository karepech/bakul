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
# FILTER SUPER KETAT (BLACKLIST & WHITELIST)
# ==========================================
JUNK_AND_UNWANTED = [
    "news", "studio", "pre-match", "post-match", "today", "update", "warm up", 
    "ceremony", "talk", "show", "weekly", "daily", "diary", "world sport", 
    "magazine", "highlight", "replay", "classic", "best of", "re-run", 
    "siaran ulang", "preview", "review", "delay", "encore", "rpt", "repeat", 
    "rewind", "recap", "recorded", "archives", "ulangan", "end of transmission", 
    "off air", "to be announced", "tba", "golden fit", "fitness", "workout", 
    "aerobic", "gym", "yoga", "documentary", "docuseries",
    "wbc", "icc", "t20", "world baseball classic", "rugby", "cricket", 
    "tennis", "wta", "atp", "wimbledon", "roland garros", "golf", "pga", 
    "wwe", "ufc", "boxing", "fight", "mma", "wrestling", "smackdown", "raw", "aew", 
    "snooker", "darts", "mlb", "nhl", "nfl", "baseball", "ice hockey", "nascar", 
    "indycar", "cycling", "ping pong", "squash", "billiard", "athletics", "swimming", 
    "gymnastics", "skiing", "snowboard", "equestrian", "sailing", "horse racing", 
    "poker", "bowling", "w-sport"
]

def is_allowed_sport(title, ch_name):
    if not title or not ch_name: return False
    t_lower = title.lower()
    c_lower = ch_name.lower()
    
    if any(k in t_lower or k in c_lower for k in JUNK_AND_UNWANTED): 
        return False
    
    whitelist = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1",
        "fc", "united", "city", "madrid", "barcelona", "chelsea", "arsenal", "liverpool",
        "juventus", "milan", "inter", "bayern", "psg", "soccer", "football", "copa", "piala",
        "afc", "aff", "fifa", "uefa",
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman",
        "voli", "volley", "vnl", "proliga", "futsal",
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint"
    ]
    
    if not (any(k in t_lower for k in whitelist) or ' vs ' in t_lower or ' v ' in t_lower):
        return False
        
    return True

def is_match_akurat(epg_name, m3u_name):
    if not epg_name or not m3u_name: return False
    epg = str(epg_name).lower().strip()
    m3u = str(m3u_name).lower().strip()

    hapus_kualitas = r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|id|my|sg|network)\b'
    epg_clean = re.sub(hapus_kualitas, '', epg).strip()
    m3u_clean = re.sub(hapus_kualitas, '', m3u).strip()

    num_epg = re.findall(r'\d+', epg_clean)
    num_m3u = re.findall(r'\d+', m3u_clean)
    if num_epg != num_m3u: 
        return False

    sub_channels = ['arena', 'bola', 'supersport', 'cricket', 'xtra', 'extra', 'now', 'grandstand', 'premier', 'badminton', 'football', 'golf']
    for sub in sub_channels:
        if bool(re.search(r'\b' + sub + r'\b', epg_clean)) != bool(re.search(r'\b' + sub + r'\b', m3u_clean)):
            return False

    epg_words = set(re.findall(r'[a-z]+', epg_clean))
    m3u_words = set(re.findall(r'[a-z]+', m3u_clean))
    
    common_words = {'astro', 'bein', 'spotv', 'hub'}
    epg_spec = epg_words - common_words
    m3u_spec = m3u_words - common_words

    if epg_spec and m3u_spec:
        if not epg_spec.intersection(m3u_spec):
            return False 
            
    return True

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
    jadwal_per_channel = {}

    if now_wib.hour < 5:
        batas_waktu_upcoming = now_wib.replace(hour=5, minute=0, second=0, microsecond=0)
    else:
        batas_waktu_upcoming = (now_wib + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)

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
                
                if ch_id and ch_name and not any(k in ch_name.lower() for k in JUNK_AND_UNWANTED):
                    if ch_id not in epg_channels:
                        epg_channels[ch_id] = ch_name.strip()
                    
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                    
                ch_name = epg_channels[ch_id]
                title_raw = prog.findtext("title") or ""
                
                if not is_allowed_sport(title_raw, ch_name): 
                    continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                
                if stop_dt <= now_wib: continue 
                if start_dt >= batas_waktu_upcoming: continue

                jam_mulai_wib = start_dt.hour
                
                if 5 <= jam_mulai_wib < 14:
                    sah_pagi = ['mls', 'concacaf', 'libertadores', 'sudamericana', 'ncaa', 'j1', 'j-league', 'k-league', 'a-league', 'badminton', 'bwf', 'motogp', 'f1']
                    is_sah_pagi = any(k in title_raw.lower() or k in ch_name.lower() for k in sah_pagi)
                    if not is_sah_pagi:
                        continue

                durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                if durasi_menit < 30: continue 

                bola_keywords = ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v']
                is_football = any(k in ch_name.lower() or k in title_raw.lower() for k in bola_keywords)
                
                non_bola_sah = ['badminton', 'bwf', 'motogp', 'f1', 'formula 1', 'voli', 'volleyball', 'futsal', 'moto2', 'moto3', 'sprint']
                is_non_bola_sah = any(k in title_raw.lower() for k in non_bola_sah)

                if is_football and not is_non_bola_sah:
                    if durasi_menit < 85:
                        continue

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

    print("\n2. Mengunduh M3U master Anda...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Meracik Playlist (1 Kategori Mutlak, Max 3 Duplikat)...")
    hasil_akhir = []
    channel_block = []
    
    event_counter = {}

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
                    bagian_atribut, nama_asli_m3u = extinf.split(",", 1)
                    nama_asli_m3u = nama_asli_m3u.strip()
                    
                    logo_asli_match = re.search(r'(?i)tvg-logo=(["\'])(.*?)\1', bagian_atribut)
                    if logo_asli_match:
                        logo_asli = logo_asli_match.group(2)
                    else:
                        logo_asli_match_no_quotes = re.search(r'(?i)tvg-logo=([^"\'\s]+)', bagian_atribut)
                        logo_asli = logo_asli_match_no_quotes.group(1) if logo_asli_match_no_quotes else ""
                    
                    # Pembersih Kategori Ekstrem (menghapus kategori yang mengandung spasi juga)
                    clean_attrs = re.sub(r'(?i)\s*group-title=(["\']?).*?\1', '', bagian_atribut)
                    clean_attrs = re.sub(r'(?i)\s*tvg-id=(["\']?).*?\1', '', clean_attrs)
                    clean_attrs = re.sub(r'(?i)\s*tvg-name=(["\']?).*?\1', '', clean_attrs)
                    clean_attrs = re.sub(r'(?i)\s*tvg-logo=(["\']?).*?\1', '', clean_attrs)
                    clean_attrs = re.sub(r'\s+', ' ', clean_attrs).strip()

                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u):
                            if ch_id in jadwal_per_channel:
                                
                                for event in jadwal_per_channel[ch_id]:
                                    jam_mulai = event["start_dt"].strftime('%H:%M')
                                    jam_selesai = event["stop_dt"].strftime('%H:%M')
                                    jam_str = f"{jam_mulai}-{jam_selesai} WIB"
                                    
                                    # SEMUANYA MASUK KE 1 FOLDER MUTLAK
                                    grup_baru = "LIVE EVENT SPORTS"
                                    
                                    if event["is_live"]:
                                        judul_akhir = f"🔴 {jam_str} - {event['title_display']}"
                                        stream_final = stream_url 
                                        order = 0
                                    else:
                                        if event["start_dt"].date() == now_wib.date():
                                            judul_akhir = f"⏳ {jam_str} - {event['title_display']}"
                                        else:
                                            judul_akhir = f"⏳ Besok {jam_str} - {event['title_display']}"
                                        stream_final = LINK_UPCOMING 
                                        order = 1
                                    
                                    counter_key = f"{ch_id}_{judul_akhir}"
                                    if event_counter.get(counter_key, 0) >= 3:
                                        continue
                                        
                                    event_counter[counter_key] = event_counter.get(counter_key, 0) + 1
                                        
                                    baris_extinf = f'{clean_attrs} group-title="{grup_baru}" tvg-id="{ch_id}" tvg-name="{nama_epg}" tvg-logo="{logo_asli}", {judul_akhir}'
                                    
                                    block_final = list(channel_block)
                                    block_final[extinf_idx] = baris_extinf
                                    
                                    hasil_akhir.append({
                                        "kategori_order": order,
                                        "start_time": event["start_dt"].timestamp(),
                                        "title_sort": event['title_display'],
                                        "baris_lengkap": block_final + [stream_final]
                                    })
            
            channel_block = []

    def sorting_logic(x):
        return (x["kategori_order"], x["start_time"], x["title_sort"])

    print("4. Menyortir Berdasarkan Jam Tayang & Menyimpan File M3U Final...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write('#EXTM3U name="🔴 OLAHRAGA AKTIF"\n')
        
        if not hasil_akhir:
            f.write('#EXTINF:-1 group-title="LIVE EVENT SPORTS", ℹ️ BELUM ADA JADWAL\n')
            f.write(f'{LINK_STANDBY}\n')
        else:
            hasil_akhir.sort(key=sorting_logic)
            
            for item in hasil_akhir:
                for blk in item["baris_lengkap"]:
                    f.write(blk + "\n")

    print(f"\nSELESAI ✔ → {len(hasil_akhir)} link event berhasil diracik ke dalam 1 Kategori/Folder!")

if __name__ == "__main__":
    main()
