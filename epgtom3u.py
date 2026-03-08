import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import io

# ==========================================
# KONFIGURASI URL
# ==========================================
EPG_URL = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4"

# ==========================================
# KATA KUNCI OLAHRAGA
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
        # Deteksi zona waktu spesifik (seperti +0800 milik StarHub Singapura)
        if len(time_str) >= 20 and ('+' in time_str or '-' in time_str):
            dt = datetime.strptime(time_str[:20], "%Y%m%d%H%M%S %z")
            dt_wib = dt.astimezone(timezone(timedelta(hours=7)))
            return dt_wib.replace(tzinfo=None)
        else:
            # Fallback jika tidak ada zona waktu, asumsikan UTC lalu ke WIB (+7)
            dt = datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
            return dt + timedelta(hours=7)
    except Exception:
        return None

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)

    print("1. Mengunduh data EPG dari GitHub (StarHub dbghelp)...")
    try:
        r_epg = requests.get(EPG_URL, timeout=60)
        r_epg.raise_for_status()
        content = r_epg.content
        
        # Perlindungan berjaga-jaga jika file dari GitHub ternyata dikompres
        if content[:2] == b'\x1f\x8b':
            content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
            
        root = ET.fromstring(content)
    except Exception as e:
        print(f"❌ Gagal mengambil EPG: {e}")
        return

    print("2. Menyaring channel Olahraga StarHub...")
    epg_channels = {}
    for ch in root.findall("channel"):
        ch_id = ch.get("id")
        ch_name = ch.findtext("display-name")
        if ch_id and ch_name and is_sport(ch_name):
            epg_channels[ch_id] = ch_name.strip()

    print(f"   -> Ditemukan {len(epg_channels)} channel olahraga.")

    print("3. Memisahkan kategori LIVE dan UPCOMING...")
    jadwal_terbaik = {}
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
            if is_live and current_best["kategori"] != "LIVE":
                jadwal_terbaik[ch_id] = {
                    "title": title.strip(), "start": start_dt, "stop": stop_dt, 
                    "kategori": "LIVE", "display_time": f"{hari_str} {jam_str}"
                }
            elif not is_live and current_best["kategori"] == "UPCOMING":
                if start_dt < current_best["start"]:
                    jadwal_terbaik[ch_id] = {
                        "title": title.strip(), "start": start_dt, "stop": stop_dt, 
                        "kategori": "UPCOMING", "display_time": f"{hari_str} {jam_str}"
                    }

    print("4. Mengunduh M3U Anda dan mencocokkan...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("5. Meracik Grup Playlist (🔴 LIVE SEKARANG & 📅 UPCOMING)...")
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

    print(f"\nSELESAI ✔ → {channel_diubah} channel olahraga berhasil disinkronkan.")

if __name__ == "__main__":
    main()
