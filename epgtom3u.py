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
    "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml", # StarHub dbghelp
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",            # Astro AqFad
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   # Indonesia AqFad (Diperbaiki ke Raw URL)
    "https://epg.pw/api/epg.xml?channel_id=397400",                                         # Spesifik Channel 397400
    "https://epg.pw/xmltv/epg_lite.xml.gz"                                                  # EPG Lite dari epg.pw (GZIP)
]

M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4"

# ==========================================
# KATA KUNCI PENJARING OLAHRAGA
# ==========================================
SPORT_KEYWORDS = [
    "sport", "bein", "spotv", "astro", "hub", "arena", "premier", 
    "champions", "euro", "football", "soccer", "liga", "nba", "motogp", 
    "badminton", "voli", "basket", "tennis", "f1", "ufc", "wwe", "setanta", "tsn",
    "espn", "supersport", "ssc", "optus", "willow", "golf", "racing", "sony ten", "eleven"
]

def is_sport(text):
    if not text: return False
    return any(k in text.lower() for k in SPORT_KEYWORDS)

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

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)

    epg_channels = {}
    jadwal_terbaik = {}

    print("1. Mengunduh dan memproses daftar EPG (Multi-Source)...")
    for url in EPG_URLS:
        print(f" -> Sedang memproses: {url.split('/')[-1].split('?')[0]} ...")
        try:
            # Timeout 120 detik karena epg_lite.xml.gz ukurannya bisa lumayan besar
            r_epg = requests.get(url, timeout=120)
            if r_epg.status_code != 200:
                print(f"    [Lewati] Gagal akses, HTTP status: {r_epg.status_code}")
                continue
                
            content = r_epg.content
            # Deteksi otomatis jika file berupa GZIP (.gz)
            if content[:2] == b'\x1f\x8b':
                print("    [Info] File GZIP terdeteksi, mengekstrak...")
                content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
                
            root = ET.fromstring(content)
            
            # Kumpulkan Channel Olahraga dari XML ini
            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                ch_name = ch.findtext("display-name")
                # HANYA kumpulkan jika mengandung unsur kata olahraga agar hemat RAM
                if ch_id and ch_name and is_sport(ch_name):
                    epg_channels[ch_id] = ch_name.strip()
                    
            # Kumpulkan Jadwal dari XML ini
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))
                title = prog.findtext("title") or "Acara Olahraga"

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                if stop_dt <= now_wib: continue
                if (stop_dt - start_dt).total_seconds() > 12 * 3600: continue

                is_live = start_dt <= now_wib < stop_dt
                kategori = "LIVE" if is_live else "UPCOMING"
                
                hari_ini = now_wib.date()
                if start_dt.date() == hari_ini:
                    hari_str = "Hari ini"
                elif start_dt.date() == hari_ini + timedelta(days=1):
                    hari_str = "Besok"
                else:
                    hari_str = start_dt.strftime("%d/%m")
                    
                jam_str = f"{start_dt.strftime('%H:%M')}-{stop_dt.strftime('%H:%M')} WIB"

                if ch_id not in jadwal_terbaik:
                    jadwal_terbaik[ch_id] = {
                        "title": title.strip(), "start": start_dt, "stop": stop_dt,
                        "kategori": kategori, "display_time": f"{hari_str} {jam_str}"
                    }
                else:
                    current_best = jadwal_terbaik[ch_id]
                    # Prioritas 1: LIVE menang melawan UPCOMING
                    if is_live and current_best["kategori"] != "LIVE":
                        jadwal_terbaik[ch_id] = {
                            "title": title.strip(), "start": start_dt, "stop": stop_dt, 
                            "kategori": "LIVE", "display_time": f"{hari_str} {jam_str}"
                        }
                    # Prioritas 2: Sama-sama UPCOMING, cari yang tayang paling duluan
                    elif not is_live and current_best["kategori"] == "UPCOMING":
                        if start_dt < current_best["start"]:
                            jadwal_terbaik[ch_id] = {
                                "title": title.strip(), "start": start_dt, "stop": stop_dt, 
                                "kategori": "UPCOMING", "display_time": f"{hari_str} {jam_str}"
                            }
        except Exception as e:
            print(f"    [Error] Melewati URL ini karena: {e}")
            continue

    print(f"\n   Total {len(epg_channels)} channel olahraga terkumpul dari {len(EPG_URLS)} sumber.")

    print("\n2. Mengunduh M3U dan mencocokkan...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Meracik Grup Playlist (🔴 LIVE SEKARANG & 📅 UPCOMING)...")
    channel_diubah = 0
    channel_block = []

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write('#EXTM3U name="🔴 OLAHRAGA AKTIF"\n')
        
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
                                if ch_id in jadwal_terbaik:
                                    acara = jadwal_terbaik[ch_id]
                                    
                                    if acara["kategori"] == "LIVE":
                                        grup_baru = '🔴 LIVE SEKARANG'
                                        status_icon = '🔴 LIVE'
                                    else:
                                        grup_baru = '📅 UPCOMING'
                                        status_icon = '⏳ NEXT'
                                        
                                    judul_final = f"{status_icon} {acara['title']} ({acara['display_time']})"
                                    
                                    clean_attrs = re.sub(r'\s*group-title="[^"]*"', '', bagian_atribut)
                                    clean_attrs = re.sub(r'\s*tvg-id="[^"]*"', '', clean_attrs)
                                    clean_attrs = re.sub(r'\s*tvg-name="[^"]*"', '', clean_attrs)
                                    
                                    channel_block[extinf_idx] = f'{clean_attrs} group-title="{grup_baru}" tvg-id="{ch_id}" tvg-name="{nama_epg}", {judul_final}'
                                    match_found = True
                                    break
                
                if match_found:
                    for blk in channel_block:
                        f.write(blk + "\n")
                    f.write(stream_url + "\n")
                    channel_diubah += 1
                
                channel_block = []

        if channel_diubah == 0:
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA JADWAL\n')
            f.write(f'{LINK_STANDBY}\n')

    print(f"\nSELESAI ✔ → {channel_diubah} channel olahraga berhasil disinkronkan dari Multi-EPG.")

if __name__ == "__main__":
    main()
