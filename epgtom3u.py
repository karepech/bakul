import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone

# ==========================================
# KONFIGURASI URL
# ==========================================
EPG_URL = "https://raw.githubusercontent.com/karepech/Epgku/refs/heads/main/epg_wib_sports.xml"
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4"

def is_match_akurat(epg_name, m3u_name):
    """
    Logika pencocokan ketat: Angka harus sama, embel-embel (HD, FHD) diabaikan.
    """
    if not epg_name or not m3u_name: return False
        
    epg_name = epg_name.lower().strip()
    m3u_name = m3u_name.lower().strip()

    num_epg_match = re.search(r'\d+', epg_name)
    num_epg = num_epg_match.group() if num_epg_match else ""
    num_m3u_match = re.search(r'\d+', m3u_name)
    num_m3u = num_m3u_match.group() if num_m3u_match else ""

    if num_epg != num_m3u: return False

    m3u_clean = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw)\b', '', m3u_name)
    epg_clean = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw)\b', '', epg_name)

    m3u_clean = re.sub(r'[^a-z0-9]', '', m3u_clean)
    epg_clean = re.sub(r'[^a-z0-9]', '', epg_clean)

    if epg_clean and m3u_clean:
        if epg_clean in m3u_clean or m3u_clean in epg_clean:
            return True
    return False

def parse_epg_time(time_str):
    """
    Membaca format zona waktu EPG (misal: +0000, +0530) dan mengonversinya MUTLAK ke WIB (+0700).
    """
    if not time_str: return None
    try:
        # Membaca datetime beserta zona waktunya (%z)
        dt = datetime.strptime(time_str.strip(), "%Y%m%d%H%M%S %z")
        # Paksa konversi ke zona waktu WIB (UTC +7)
        dt_wib = dt.astimezone(timezone(timedelta(hours=7)))
        # Hilangkan info timezone agar bisa dibandingkan dengan now_wib (waktu lokal komputer)
        return dt_wib.replace(tzinfo=None)
    except ValueError:
        # Fallback jika string EPG tidak memiliki info timezone
        try:
            return datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
        except:
            return None

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)

    print("1. Mengunduh dan memproses data EPG...")
    try:
        r_epg = requests.get(EPG_URL, timeout=30)
        r_epg.raise_for_status()
        root = ET.fromstring(r_epg.content)
    except Exception as e:
        print(f"❌ Gagal mengambil EPG: {e}")
        return

    epg_channels = {}
    for ch in root.findall("channel"):
        ch_id = ch.get("id")
        ch_name = ch.findtext("display-name")
        if ch_id and ch_name:
            epg_channels[ch_id] = ch_name.strip()

    jadwal_aktif = {}
    for prog in root.findall("programme"):
        ch_id = prog.get("channel")
        start_dt = parse_epg_time(prog.get("start"))
        stop_dt = parse_epg_time(prog.get("stop"))
        title = prog.findtext("title") or "Acara Olahraga"

        # Buang data rusak jika ada jadwal yang jam berhentinya lebih awal dari jam mulainya
        if not start_dt or not stop_dt or not ch_id or start_dt >= stop_dt:
            continue

        # LOGIKA PEMILIHAN JADWAL BARU YANG LEBIH CERDAS
        # 1. Prioritas Pertama: Acara sedang LIVE detik ini
        if start_dt <= now_wib < stop_dt:
            jadwal_aktif[ch_id] = {
                "title": title.strip(),
                "start": start_dt,
                "stop": stop_dt,
                "status": "🔴 LIVE"
            }
        # 2. Prioritas Kedua: Acara NEXT (akan datang)
        elif start_dt > now_wib:
            if ch_id not in jadwal_aktif:
                jadwal_aktif[ch_id] = {"title": title.strip(), "start": start_dt, "stop": stop_dt, "status": "⏳ NEXT"}
            else:
                # Jangan pernah menimpa jadwal LIVE dengan jadwal NEXT
                if jadwal_aktif[ch_id].get("status") != "🔴 LIVE":
                    # Kalau dua-duanya NEXT, pilih jam tayang yang paling dekat dengan saat ini
                    if start_dt < jadwal_aktif[ch_id]["start"]:
                        jadwal_aktif[ch_id] = {"title": title.strip(), "start": start_dt, "stop": stop_dt, "status": "⏳ NEXT"}

    print("2. Mengunduh dan membaca M3U...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Meracik M3U (Sinkronisasi Zona Waktu)...")
    channel_diubah = 0
    channel_block = []

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write('#EXTM3U name="🔴 LIVE SPORTS"\n')
        
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
                                if ch_id in jadwal_aktif:
                                    acara = jadwal_aktif[ch_id]
                                    jam_tayang = f"{acara['start'].strftime('%H:%M')} - {acara['stop'].strftime('%H:%M')} WIB"
                                    
                                    # Format Nama Baru: 🔴 LIVE Judul Acara (Jam Tayang)
                                    judul_final = f"{acara['status']} {acara['title']} ({jam_tayang})"
                                    
                                    clean_attrs = re.sub(r'\s*tvg-id="[^"]*"', '', bagian_atribut)
                                    clean_attrs = re.sub(r'\s*tvg-name="[^"]*"', '', clean_attrs)
                                    
                                    channel_block[extinf_idx] = f'{clean_attrs} tvg-id="{ch_id}" tvg-name="{nama_epg}", {judul_final}'
                                    match_found = True
                                    break
                
                if match_found:
                    for blk in channel_block:
                        f.write(blk + "\n")
                    f.write(stream_url + "\n")
                    channel_diubah += 1
                
                channel_block = []

        if channel_diubah == 0:
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA SIARAN LIVE SAAT INI\n')
            f.write(f'{LINK_STANDBY}\n')

    print(f"\nSELESAI ✔ → {channel_diubah} siaran langsung berhasil diracik dengan zona waktu yang benar.")

if __name__ == "__main__":
    main()
