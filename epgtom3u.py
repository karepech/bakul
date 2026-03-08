import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta

# ==========================================
# KONFIGURASI URL
# ==========================================
EPG_URL = "https://raw.githubusercontent.com/karepech/Epgku/refs/heads/main/epg_wib_sports.xml"
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
OUTPUT_FILE = "live_matches_only.m3u"

def is_match_akurat(epg_name, m3u_name):
    """
    Mencocokkan nama channel EPG dan M3U dengan logika ketat pada angka.
    """
    if not epg_name or not m3u_name:
        return False
        
    epg_name = epg_name.lower().strip()
    m3u_name = m3u_name.lower().strip()

    # 1. Ekstrak angka pertama yang muncul di nama channel
    num_epg_match = re.search(r'\d+', epg_name)
    num_epg = num_epg_match.group() if num_epg_match else ""
    
    num_m3u_match = re.search(r'\d+', m3u_name)
    num_m3u = num_m3u_match.group() if num_m3u_match else ""

    # ATURAN MUTLAK 1: Angka harus sama persis.
    # Jika epg="Setanta 1" (1) dan m3u="Setanta 2" (2) -> GAGAL
    # Jika epg="Hub Primer 1" (1) dan m3u="Hub Primer" ("") -> GAGAL
    if num_epg != num_m3u:
        return False

    # 2. Bersihkan embel-embel kualitas gambar (HD, FHD, 4K, TV)
    m3u_clean = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw)\b', '', m3u_name)
    epg_clean = re.sub(r'\b(hd|fhd|uhd|4k|tv|hevc|raw)\b', '', epg_name)

    # 3. Hapus semua spasi dan karakter selain huruf/angka untuk pencocokan final
    m3u_clean = re.sub(r'[^a-z0-9]', '', m3u_clean)
    epg_clean = re.sub(r'[^a-z0-9]', '', epg_clean)

    # ATURAN MUTLAK 2: Base name (tanpa angka dan HD) harus beririsan
    if epg_clean and m3u_clean:
        if epg_clean in m3u_clean or m3u_clean in epg_clean:
            return True
            
    return False

def parse_epg_time(time_str):
    if not time_str: return None
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

    # Petakan semua channel EPG (Menyimpan ID dan Nama Aslinya)
    epg_channels = {}
    for ch in root.findall("channel"):
        ch_id = ch.get("id")
        ch_name = ch.findtext("display-name")
        if ch_id and ch_name:
            epg_channels[ch_id] = ch_name.strip()

    # Cari jadwal yang sedang/akan tayang
    jadwal_aktif = {}
    for prog in root.findall("programme"):
        ch_id = prog.get("channel")
        start_dt = parse_epg_time(prog.get("start"))
        stop_dt = parse_epg_time(prog.get("stop"))
        title = prog.findtext("title") or "Acara Olahraga"

        if not start_dt or not stop_dt or not ch_id:
            continue

        if stop_dt > now_wib:
            if ch_id not in jadwal_aktif or start_dt < jadwal_aktif[ch_id]["start"]:
                jadwal_aktif[ch_id] = {
                    "title": title.strip(),
                    "start": start_dt,
                    "stop": stop_dt
                }

    print("2. Mengunduh dan membaca M3U...")
    try:
        r_m3u = requests.get(M3U_URL, timeout=30)
        r_m3u.raise_for_status()
        m3u_lines = r_m3u.text.splitlines()
    except Exception as e:
        print(f"❌ Gagal mengambil file M3U: {e}")
        return

    print("3. Meracik M3U (Hanya menyimpan yang Live & Cocok)...")
    channel_diubah = 0
    channel_block = []

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write('#EXTM3U name="🔴 LIVE MATCHES"\n')
        
        for line in m3u_lines:
            baris = line.strip()
            if not baris: continue
            
            # Abaikan header global M3U agar tidak dobel
            if baris.upper().startswith("#EXTM3U"):
                continue

            if baris.startswith("#"):
                channel_block.append(baris)
            else:
                # Ini adalah baris URL, berarti 1 blok channel sudah lengkap terkumpul
                stream_url = baris
                match_found = False
                
                # Cari baris EXTINF di dalam blok yang terkumpul
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
                        
                        # CEK KECOCOKAN DENGAN SEMUA DATA EPG
                        for ch_id, nama_epg in epg_channels.items():
                            if is_match_akurat(nama_epg, nama_asli_m3u):
                                # Jika nama cocok, cek apakah ada jadwal aktifnya
                                if ch_id in jadwal_aktif:
                                    acara = jadwal_aktif[ch_id]
                                    jam_tayang = f"{acara['start'].strftime('%H:%M')} - {acara['stop'].strftime('%H:%M')} WIB"
                                    judul_final = f"🔴 {acara['title']} ({jam_tayang})"
                                    
                                    # Hapus tvg-id/tvg-name lama dan masukkan yang baru
                                    clean_attrs = re.sub(r'\s*tvg-id="[^"]*"', '', bagian_atribut)
                                    clean_attrs = re.sub(r'\s*tvg-name="[^"]*"', '', clean_attrs)
                                    
                                    # Timpa baris EXTINF di memori
                                    channel_block[extinf_idx] = f'{clean_attrs} tvg-id="{ch_id}" tvg-name="{nama_epg}", {judul_final}'
                                    match_found = True
                                    break # Keluar dari loop pencarian channel karena sudah ketemu
                
                # JIKA KETEMU DAN ADA JADWAL -> TULIS KE FILE
                if match_found:
                    for blk in channel_block:
                        f.write(blk + "\n")
                    f.write(stream_url + "\n")
                    channel_diubah += 1
                
                # Reset blok untuk membaca channel selanjutnya (Channel yang tidak match otomatis terbuang/tidak ditulis)
                channel_block = []

        # Fallback jika ternyata jam tersebut sama sekali tidak ada pertandingan di semua channel
        if channel_diubah == 0:
            print("ℹ️ Tidak ada jadwal live satupun saat ini.")
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA SIARAN LIVE SAAT INI\n')
            f.write(f'{LINK_STANDBY}\n')

    print(f"\nSELESAI ✔ → {channel_diubah} siaran langsung berhasil diracik ke dalam M3U.")

if __name__ == "__main__":
    main()
