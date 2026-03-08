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
    "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml", 
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",            
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://epg.pw/api/epg.xml?channel_id=397400",                                         
    "https://epg.pw/xmltv/epg_lite.xml.gz"                                                  
]

M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4"

# ==========================================
# KATA KUNCI FILTERING
# ==========================================
SPORT_KEYWORDS = [
    "sport", "bein", "spotv", "astro", "hub", "arena", "premier", 
    "champions", "euro", "football", "soccer", "liga", "nba", "motogp", 
    "badminton", "voli", "basket", "tennis", "f1", "ufc", "wwe", "setanta", "tsn",
    "espn", "supersport", "ssc", "optus", "willow", "golf", "racing", "sony ten", "eleven"
]

REPLAY_KEYWORDS = [
    "highlight", "replay", "classic", "best of", "re-run", "siaran ulang", 
    "magazine", "preview", "review", "delay", "encore", "rpt", "repeat", 
    "rewind", "recap", "recorded", "archives", "ulangan"
]

def is_sport(text):
    if not text: return False
    return any(k in text.lower() for k in SPORT_KEYWORDS)

def is_fresh_live(prog, title, channel_name):
    if prog.find("previously-shown") is not None:
        return False
    if not title: 
        return False
    t = title.lower()
    c = channel_name.lower()
    
    if any(k in t for k in REPLAY_KEYWORDS):
        return False
        
    if any(network in c for network in ['bein', 'spotv', 'astro', 'champions', 'premier', 'hub']):
        if 'vs' in t or ' v ' in t:
            if not re.search(r'\b(live|\(l\)|\[l\])\b', t):
                return False 
                
    return True

def is_match_akurat(epg_name, m3u_name):
    if not epg_name or not m3u_name: return False
        
    epg_name = epg_name.lower().strip()
    m3u_name = m3u_name.lower().strip()

    num_epg_match = re.search(r'\d+', epg_name)
    num_epg = num_epg_match.group() if num_epg_match else ""
    num_m3u_match = re.search(r'\d+', m3u_name)
    num_m3u = num_m3u_match.group() if num_m3u_match else ""

    if num_epg != num_m3u: return False

    m3u_clean = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw|plus|max)\b', '', m3u_name)
    epg_clean = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw|plus|max)\b', '', epg_name)
    m3u_clean = re.sub(r'[^a-z0-9]', '', m3u_clean)
    epg_clean = re.sub(r'[^a-z0-9]', '', epg_clean)

    if epg_clean and m3u_clean:
        return epg_clean in m3u_clean or m3u_clean in epg_clean
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

def get_sort_key(name):
    parts = re.split(r'(\d+)', name.lower())
    return [int(p) if p.isdigit() else p.strip() for p in parts]

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels = {}
    
    jadwal_live = {}
    jadwal_upcoming = {}

    print("1. Mengunduh dan memproses daftar EPG (Multi-Source)...")
    for url in EPG_URLS:
        print(f" -> Sedang memproses: {url.split('/')[-1].split('?')[0]} ...")
        try:
            r_epg = requests.get(url, timeout=120)
            if r_epg.status_code != 200:
                print(f"    [Lewati] Gagal akses, HTTP status: {r_epg.status_code}")
                continue
                
            content = r_epg.content
            if content[:2] == b'\x1f\x8b':
                content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
                
            root = ET.fromstring(content)
            
            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                ch_name = ch.findtext("display-name")
                if ch_id and ch_name and is_sport(ch_name):
                    epg_channels[ch_id] = ch_name.strip()
                    
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                    
                ch_name = epg_channels[ch_id]
                title = prog.findtext("title") or ""
                
                if not is_fresh_live(prog, title, ch_name): 
                    continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                if stop_dt <= now_wib: continue 
                if (stop_dt - start_dt).total_seconds() > 12 * 3600: continue

                # =========================================================
                # FILTER MUTLAK: HANYA IZINKAN ACARA JAM 17:00 s/d 04:59 WIB
                # =========================================================
                jam_mulai = start_dt.hour
                # Jika jam mulai BUKAN di atas jam 17 sore ATAU BUKAN di bawah jam 5 subuh, BUANG!
                if not (jam_mulai >= 17 or jam_mulai < 5):
                    continue 

                waktu_toleransi_live = start_dt - timedelta(minutes=5)
                is_live = waktu_toleransi_live <= now_wib < stop_dt
                
                hari_ini = now_wib.date()
                if start_dt.date() == hari_ini:
                    hari_str = "Hari ini"
                elif start_dt.date() == hari_ini + timedelta(days=1):
                    hari_str = "Besok"
                else:
                    hari_str = start_dt.strftime("%d/%m")
                    
                jam_str = f"{start_dt.strftime('%H:%M')}-{stop_dt.strftime('%H:%M')} WIB"

                if is_live:
                    if ch_id not in jadwal_live or start_dt < jadwal_live[ch_id]["start"]:
                        jadwal_live[ch_id] = {
                            "title": title.strip(), "start": start_dt, "stop": stop_dt,
                            "display_time": f"{hari_str} {jam_str}"
                        }
                else:
                    if ch_id not in jadwal_upcoming or start_dt < jadwal_upcoming[ch_id]["start"]:
                        jadwal_upcoming[ch_id] = {
                            "title": title.strip(), "start": start_dt, "stop": stop_dt,
                            "display_time": f"{hari_str} {jam_str}"
                        }
        except Exception as e:
            print(f"    [Error] Melewati URL ini karena: {e}")
            continue

    print("\n2. Mengunduh M3U sumber...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Mencocokkan EPG dan Menggandakan Channel untuk LIVE & UPCOMING...")
    
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
            match_found = False
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
                    
                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u):
                            clean_attrs = re.sub(r'(?i)\s*group-title=(["\']?)[^"\'\s]+\1', '', bagian_atribut)
                            clean_attrs = re.sub(r'(?i)\s*tvg-id=(["\']?)[^"\'\s]+\1', '', clean_attrs)
                            clean_attrs = re.sub(r'(?i)\s*tvg-name=(["\']?)[^"\'\s]+\1', '', clean_attrs)
                            clean_attrs = re.sub(r'\s+', ' ', clean_attrs).strip()

                            if ch_id in jadwal_live:
                                acara = jadwal_live[ch_id]
                                judul_final = f"🔴 LIVE {acara['title']} ({acara['display_time']})"
                                
                                block_live = list(channel_block) 
                                block_live[extinf_idx] = f'{clean_attrs} group-title="🔴 LIVE SEKARANG" tvg-id="{ch_id}" tvg-name="{nama_epg}", {judul_final}'
                                
                                hasil_akhir.append({
                                    "kategori_order": 0,
                                    "sort_name": get_sort_key(nama_asli_m3u),
                                    "start_time": acara["start"],
                                    "baris_lengkap": block_live + [stream_url]
                                })
                                match_found = True

                            if ch_id in jadwal_upcoming:
                                acara = jadwal_upcoming[ch_id]
                                judul_final = f"⏳ NEXT {acara['title']} ({acara['display_time']})"
                                
                                block_upcoming = list(channel_block) 
                                block_upcoming[extinf_idx] = f'{clean_attrs} group-title="📅 UPCOMING" tvg-id="{ch_id}" tvg-name="{nama_epg}", {judul_final}'
                                
                                hasil_akhir.append({
                                    "kategori_order": 1,
                                    "sort_name": get_sort_key(nama_asli_m3u),
                                    "start_time": acara["start"],
                                    "baris_lengkap": block_upcoming + [stream_url]
                                })
                                match_found = True
                            
                            if match_found:
                                break
            
            channel_block = []

    print("4. Menyortir Abjad & Menyimpan File M3U Final...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write('#EXTM3U name="🔴 OLAHRAGA AKTIF"\n')
        
        if not hasil_akhir:
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA JADWAL LIVE\n')
            f.write(f'{LINK_STANDBY}\n')
        else:
            hasil_akhir.sort(key=lambda x: (x["kategori_order"], x["sort_name"], x["start_time"]))
            
            for item in hasil_akhir:
                for blk in item["baris_lengkap"]:
                    f.write(blk + "\n")

    print(f"\nSELESAI ✔ → {len(hasil_akhir)} pertandingan berhasil diracik (Telah di-filter dari jam 17:00 - 05:00 WIB).")

if __name__ == "__main__":
    main()
