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
# KATA KUNCI FILTERING
# ==========================================
SPORT_KEYWORDS = ["sport", "bein", "spotv", "astro", "hub", "arena", "premier", "champions", "euro", "football", "soccer", "liga", "nba", "motogp", "badminton", "voli", "basket", "tennis", "f1", "ufc", "wwe"]

# Kata kunci sampah yang Wajib Dihapus
JUNK_KEYWORDS = [
    "highlight", "replay", "classic", "best of", "re-run", "siaran ulang", 
    "magazine", "preview", "review", "delay", "encore", "rpt", "repeat", 
    "rewind", "recap", "recorded", "archives", "ulangan", "end of transmission", 
    "off air", "to be announced", "tba", "news", "studio", "pre-match", 
    "post-match", "today", "update", "warm up", "ceremony", "talk", "show",
    "weekly", "daily", "diary", "world sport"
]

# Kata kunci olahraga yang DILARANG masuk (Tenis, Basket, dll)
UNWANTED_SPORTS = [
    "nba", "basketball", "basket", "tennis", "wta", "atp", "golf", "wwe", "ufc", 
    "boxing", "snooker", "darts", "rugby", "cricket", "mlb", "nhl", "nfl", 
    "nascar", "indycar", "cycling", "ping pong", "squash"
]

def is_sport(text):
    if not text: return False
    return any(k in text.lower() for k in SPORT_KEYWORDS)

def is_fresh_live(prog, title):
    if prog.find("previously-shown") is not None: return False
    if not title: return False
    t = title.lower()
    
    if any(k in t for k in JUNK_KEYWORDS): return False
    if any(k in t for k in UNWANTED_SPORTS): return False
    return True

def is_match_akurat(epg_name, m3u_name):
    if not epg_name or not m3u_name: return False
    epg = str(epg_name).lower().strip()
    m3u = str(m3u_name).lower().strip()

    hapus_kualitas = r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|id|my|sg)\b'
    epg_clean = re.sub(hapus_kualitas, '', epg).strip()
    m3u_clean = re.sub(hapus_kualitas, '', m3u).strip()

    # WAJIB SAMA ANGKA
    num_epg = re.findall(r'\d+', epg_clean)
    num_m3u = re.findall(r'\d+', m3u_clean)
    if num_epg != num_m3u: 
        return False

    # =============================================================
    # PENGUNCI KAMAR ASTRO & BEIN (Mencegah Salah Kamar Mutlak)
    # =============================================================
    if ('arena' in epg_clean) != ('arena' in m3u_clean): return False
    if ('bola' in epg_clean) != ('bola' in m3u_clean): return False # Mengunci Astro Arena Bola
    if ('supersport' in epg_clean) != ('supersport' in m3u_clean): return False
    if ('cricket' in epg_clean) != ('cricket' in m3u_clean): return False
    if ('xtra' in epg_clean or 'extra' in epg_clean) != ('xtra' in m3u_clean or 'extra' in m3u_clean): return False
    if ('now' in epg_clean) != ('now' in m3u_clean): return False

    epg_huruf = re.sub(r'[^a-z]', '', epg_clean)
    m3u_huruf = re.sub(r'[^a-z]', '', m3u_clean)

    if epg_huruf and m3u_huruf:
        if epg_huruf in m3u_huruf or m3u_huruf in epg_huruf:
            return True
            
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
    jadwal_per_channel = {}

    # SIKLUS 24 JAM (Jam 05:00 s/d 04:59 esok harinya)
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
                if ch_id and ch_name and is_sport(ch_name):
                    if ch_id not in epg_channels:
                        epg_channels[ch_id] = ch_name.strip()
                    
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                    
                ch_name = epg_channels[ch_id]
                title_raw = prog.findtext("title") or ""
                if not is_fresh_live(prog, title_raw): continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                
                # Buang yang sudah berlalu dan melewati batas jam 04:59 besok
                if stop_dt <= now_wib: continue 
                if start_dt >= batas_waktu_upcoming: continue

                # ==========================================================
                # ALGORITMA FILTER WAKTU LIGA EROPA (MUSTAHIL PAGI/SIANG)
                # ==========================================================
                jam_mulai_wib = start_dt.hour
                kata_eropa = ['premier league', 'champions league', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'la liga', 'laliga', 'uefa', 'europa', 'euro']
                
                is_euro_football = any(k in title_raw.lower() or k in ch_name.lower() for k in kata_eropa)
                
                # Jika itu Liga Eropa dan tayang antara jam 05:00 pagi sampai 18:00 sore (WIB), itu PASTI SIARAN ULANG -> Buang!
                # (Acara Bola Asia & Amerika bebas dari blokir ini karena tidak punya kata_eropa di judulnya)
                if is_euro_football and (5 <= jam_mulai_wib < 18):
                    continue

                # ==========================================================
                # FILTER DURASI SEPAK BOLA (Wajib >= 85 Menit)
                # ==========================================================
                durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                
                if durasi_menit < 30: 
                    continue 

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

    print("3. Meracik Playlist (Max 3 Duplikat Per Channel, Logo Asli M3U)...")
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
                    
                    clean_attrs = re.sub(r'(?i)\s*group-title=(["\']?)[^"\'\s]+\1', '', bagian_atribut)
                    clean_attrs = re.sub(r'(?i)\s*tvg-id=(["\']?)[^"\'\s]+\1', '', clean_attrs)
                    clean_attrs = re.sub(r'(?i)\s*tvg-name=(["\']?)[^"\'\s]+\1', '', clean_attrs)
                    clean_attrs = re.sub(r'(?i)\s*tvg-logo=(["\']?)[^"\'\s]+\1', '', clean_attrs)
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
                                    
                                    # SISTEM LIMIT MAKSIMAL 3 DUPLIKAT
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
