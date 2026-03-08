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
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

def is_allowed_sport(title):
    """FILTER 1: PENYARINGAN SUPER KETAT"""
    if not title: return False
    t = title.lower()
    
    # 1. HANCURKAN JIKA ADA HURUF CINA / JEPANG / ARAB
    if re.search(r'[\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', title):
        return False

    # 2. BLACKLIST KATA SAMPAH & OLAHRAGA HARAM
    haram = [
        "news", "studio", "pre-match", "post-match", "update", "talk", "show", "weekly", 
        "magazine", "highlight", "replay", "classic", "re-run", "siaran ulang", "review", 
        "delay", "encore", "recorded", "archives", "tba", "fitness", "workout", "gym", "golden fit",
        "tennis", "wta", "atp", "wimbledon", "golf", "pga", "wwe", "ufc", "boxing", "fight", "mma", 
        "smackdown", "snooker", "darts", "rugby", "cricket", "icc", "mlb", "nhl", "nfl", "baseball", 
        "wbc", "basketball", "nba", "fiba", "movie", "special delivery"
    ]
    if any(h in t for h in haram): return False
    
    # 3. WHITELIST OLAHRAGA SAH (Bola, Voli, Futsal, Badminton, Motogp, F1)
    halal = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", 
        "fc", "united", "city", "madrid", "barcelona", "chelsea", "arsenal", "liverpool", 
        "juventus", "milan", "inter", "bayern", "psg", "soccer", "football", "copa", "piala", 
        "afc", "aff", "fifa", "uefa", 
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", 
        "voli", "volley", "vnl", "proliga", "futsal", 
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint"
    ]
    is_halal = any(h in t for h in halal)
    
    # Loloskan jika ada kata halal, ATAU jika ada tulisan " VS " (Laga resmi)
    if is_halal or ' vs ' in t or ' v ' in t:
        return True
        
    return False

def is_match_akurat(epg_name, m3u_name):
    """FILTER 2: PENGUNCI KAMAR MUTLAK (ANTI-NYASAR)"""
    if not epg_name or not m3u_name: return False
    e = epg_name.lower().strip()
    m = m3u_name.lower().strip()

    # KUNCI ASTRO
    if 'astro' in e:
        if 'astro' not in m: return False
        subs = ['arena bola 2', 'arena bola', 'arena', 'supersport 1', 'supersport 2', 'supersport 3', 'supersport 4', 'supersport 5', 'supersport', 'cricket', 'grandstand', 'badminton', 'football', 'golf']
        s_e = next((s for s in subs if s in e), 'unknown')
        s_m = next((s for s in subs if s in m), 'unknown')
        return s_e == s_m
        
    # KUNCI BEIN
    if 'bein' in e:
        if 'bein' not in m: return False
        n_e = re.findall(r'\d+', e)
        n_m = re.findall(r'\d+', m)
        if n_e and n_m and n_e[0] != n_m[0]: return False
        if ('xtra' in e or 'extra' in e) != ('xtra' in m or 'extra' in m): return False
        return True
        
    # KUNCI SPOTV
    if 'spotv' in e:
        if 'spotv' not in m: return False
        n_e = re.findall(r'\d+', e)
        n_m = re.findall(r'\d+', m)
        if n_e and n_m and n_e[0] != n_m[0]: return False
        if ('now' in e) != ('now' in m): return False
        return True
        
    # KUNCI UMUM (Sportstars, Soccer Channel, dll)
    e_clean = re.sub(r'[^a-z0-9]', '', e)
    m_clean = re.sub(r'[^a-z0-9]', '', m)
    return e_clean in m_clean or m_clean in e_clean

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

    # SIKLUS 24 JAM (05:00 - 04:59 Besok)
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
                
                # UJI SARINGAN KETAT
                if not is_allowed_sport(title_raw): continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                
                # Buang Masa Lalu dan Masa Depan (Lebih dari jam 04:59 besok)
                if stop_dt <= now_wib: continue 
                if start_dt >= batas_waktu_upcoming: continue

                # ==========================================================
                # FILTER PEMBANTAI REPLAY LIGA EROPA (Jam 05:00 - 17:59 WIB)
                # ==========================================================
                jam_mulai_wib = start_dt.hour
                if 5 <= jam_mulai_wib < 18:
                    bola_eropa = ['premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'la liga', 'laliga', 'uefa', 'europa']
                    is_eropa = any(k in title_raw.lower() or k in ch_name.lower() for k in bola_eropa)
                    
                    # Jika itu liga Eropa dan tayang jam 5 pagi s/d 6 sore = PASTI REPLAY! BUANG!
                    if is_eropa:
                        continue

                # ==========================================================
                # FILTER DURASI SEPAK BOLA (Wajib >= 85 Menit)
                # ==========================================================
                durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                if durasi_menit < 30: continue # Buang berita 15-20 menit
                
                bola_keywords = ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v']
                is_football = any(k in ch_name.lower() or k in title_raw.lower() for k in bola_keywords)
                non_bola_sah = ['badminton', 'bwf', 'motogp', 'f1', 'formula', 'voli', 'volleyball', 'futsal', 'moto2', 'moto3', 'sprint']
                is_non_bola_sah = any(k in title_raw.lower() for k in non_bola_sah)

                # Paksa bola minimal 85 menit
                if is_football and not is_non_bola_sah:
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

    print("\n2. Mengunduh M3U master Anda...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Meracik Playlist...")
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
                    
                    # LOGO ASLI 100%
                    logo_asli_match = re.search(r'(?i)tvg-logo=(["\'])(.*?)\1', bagian_atribut)
                    logo_asli = logo_asli_match.group(2) if logo_asli_match else ""
                    
                    # PEMBERSIHAN ATRIBUT YANG MENGHANCURKAN FOLDER TIVIMATE TELAH DIPERBAIKI (Pakai format ["\'][^"\']*["\'])
                    clean_attrs = re.sub(r'(?i)\s*group-title=["\'][^"\']*["\']', '', bagian_atribut)
                    clean_attrs = re.sub(r'(?i)\s*tvg-id=["\'][^"\']*["\']', '', clean_attrs)
                    clean_attrs = re.sub(r'(?i)\s*tvg-name=["\'][^"\']*["\']', '', clean_attrs)
                    clean_attrs = re.sub(r'(?i)\s*tvg-logo=["\'][^"\']*["\']', '', clean_attrs)
                    clean_attrs = re.sub(r'\s+', ' ', clean_attrs).strip()

                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u):
                            if ch_id in jadwal_per_channel:
                                
                                for event in jadwal_per_channel[ch_id]:
                                    jam_mulai = event["start_dt"].strftime('%H:%M')
                                    jam_selesai = event["stop_dt"].strftime('%H:%M')
                                    jam_str = f"{jam_mulai}-{jam_selesai} WIB"
                                    
                                    if event["is_live"]:
                                        grup_baru = "🔴 LIVE EVENT SPORTS"
                                        judul_akhir = f"🔴 {jam_str} - {event['title_display']}"
                                        stream_final = stream_url 
                                        order = 0
                                    else:
                                        grup_baru = "📅 UPCOMING EVENT"
                                        if event["start_dt"].date() == now_wib.date():
                                            judul_akhir = f"⏳ {jam_str} - {event['title_display']}"
                                        else:
                                            judul_akhir = f"⏳ Besok {jam_str} - {event['title_display']}"
                                        stream_final = LINK_UPCOMING 
                                        order = 1
                                    
                                    # LIMIT DUPLIKAT MAKSIMAL 3 PER ACARA
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
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA JADWAL\n')
            f.write(f'{LINK_STANDBY}\n')
        else:
            hasil_akhir.sort(key=sorting_logic)
            
            for item in hasil_akhir:
                for blk in item["baris_lengkap"]:
                    f.write(blk + "\n")

    print(f"\nSELESAI ✔ → {len(hasil_akhir)} link event premium berhasil diracik!")

if __name__ == "__main__":
    main()
