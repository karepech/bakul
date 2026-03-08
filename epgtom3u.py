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

def bersihkan_nama(nama):
    """Membersihkan nama channel untuk akurasi pencocokan."""
    if not nama: return ""
    return re.sub(r'[^a-z0-9]', '', nama.lower())

def parse_epg_time(time_str):
    """Mengubah format waktu EPG 'YYYYMMDDHHMMSS +0700' menjadi format waktu Python."""
    if not time_str: return None
    try:
        # Ambil 14 digit pertama (YYYYMMDDHHMMSS)
        return datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
    except:
        return None

def main():
    # Ambil waktu saat ini dalam zona WIB (UTC +7)
    now_wib = datetime.utcnow() + timedelta(hours=7)

    print("1. Mengunduh dan memproses data EPG...")
    try:
        r_epg = requests.get(EPG_URL, timeout=30)
        r_epg.raise_for_status()
        root = ET.fromstring(r_epg.content)
    except Exception as e:
        print(f"❌ Gagal mengambil EPG: {e}")
        return

    # A. Petakan Nama Channel ke ID Channel EPG
    epg_channels = {}
    for ch in root.findall("channel"):
        ch_id = ch.get("id")
        ch_name = ch.findtext("display-name")
        if ch_id and ch_name:
            epg_channels[bersihkan_nama(ch_name)] = ch_id

    # B. Cari jadwal yang sedang/akan tayang untuk masing-masing channel
    jadwal_aktif = {}
    for prog in root.findall("programme"):
        ch_id = prog.get("channel")
        start_dt = parse_epg_time(prog.get("start"))
        stop_dt = parse_epg_time(prog.get("stop"))
        title = prog.findtext("title") or "Acara Olahraga"

        if not start_dt or not stop_dt or not ch_id:
            continue

        # Cek jika jadwal belum selesai (masih tayang atau akan datang)
        if stop_dt > now_wib:
            # Ambil jadwal yang paling dekat waktunya dengan jam saat ini
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

    print("3. Meracik Playlist M3U dengan Jadwal Langsung...")
    channel_diubah = 0

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for line in m3u_lines:
            baris = line.strip()
            if not baris: continue

            if baris.startswith("#EXTINF"):
                # Pisahkan bagian atribut (kiri) dan nama channel (kanan)
                if "," in baris:
                    bagian_atribut, nama_asli_m3u = baris.rsplit(",", 1)
                    nama_asli_m3u = nama_asli_m3u.strip()
                    kunci_m3u = bersihkan_nama(nama_asli_m3u)

                    judul_final = nama_asli_m3u # Default: gunakan nama asli jika tak ada jadwal

                    # Cek apakah nama channel ada di EPG
                    if kunci_m3u in epg_channels:
                        ch_id = epg_channels[kunci_m3u]
                        
                        # Cek apakah channel tersebut ada jadwal yang sedang/akan tayang
                        if ch_id in jadwal_aktif:
                            acara = jadwal_aktif[ch_id]
                            jam_tayang = f"{acara['start'].strftime('%H:%M')} - {acara['stop'].strftime('%H:%M')} WIB"
                            
                            # RUMUS PENGGANTIAN NAMA: "Judul Acara (Jam Tayang)"
                            judul_final = f"{acara['title']} ({jam_tayang})"
                            channel_diubah += 1

                    # Gabungkan kembali atribut utuh dengan Judul yang baru
                    f.write(f"{bagian_atribut}, {judul_final}\n")
                else:
                    f.write(baris + "\n")
            else:
                # Tulis link stream atau tag seperti #EXTGRP apa adanya
                f.write(baris + "\n")

    print(f"\nSELESAI ✔ → {channel_diubah} channel berhasil diganti namanya dengan jadwal pertandingan.")
    print(f"File hasil disimpan sebagai: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
