import requests
import gzip
import xml.etree.ElementTree as ETimport requests
import cloudscraper
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
import os
from io import BytesIO

# 1. Konfigurasi URL
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"
]

# 2. Fungsi Normalisasi (Rumus Otomatis)
def rumus_samakan_teks(teks):
    if not teks: return ""
    teks = teks.lower()
    teks = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network)\b', '', teks)
    teks = re.sub(r'\[.*?\]|\(.*?\)', '', teks)
    teks = re.sub(r'[^a-z0-9]', '', teks)
    return teks

# 3. Baca Kamus Mapping Manual (Jika ada file kamus_mapping.txt)
kamus_manual = {}
if os.path.exists("kamus_mapping.txt"):
    with open("kamus_mapping.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                parts = line.strip().split("=")
                if len(parts) == 3:
                    id_epg = parts[0].strip()
                    target_m3u = parts[1].strip().lower()
                    nama_baru = parts[2].strip()
                    kamus_manual[target_m3u] = {"epg": id_epg, "nama": nama_baru}

print("1. Mengunduh dan memproses data EPG...")
epg_dict = {} 
kamus_rumus_epg = {} 

# Bypass Cloudflare / Anti-Bot
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

for url in EPG_URLS:
    try:
        print(f"Mengakses: {url}")
        if "epgshare01" in url:
            resp = scraper.get(url, timeout=60)
        else:
            resp = requests.get(url, timeout=30)
            
        if b'<html' in resp.content[:20].lower() or b'<!doctype' in resp.content[:20].lower():
            print(f"⚠️ SKIP: Link {url} diblokir (mendapat HTML).")
            continue
            
        if url.endswith('.gz'):
            content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read()
        else:
            content = resp.content
            
        root = ET.fromstring(content)
        for ch in root.findall('channel'):
            id_asli_epg = ch.get('id')
            display = ch.find('display-name')
            nama_epg = display.text if display is not None and display.text else id_asli_epg
            
            if id_asli_epg:
                epg_dict[id_asli_epg] = nama_epg
                kamus_rumus_epg[rumus_samakan_teks(id_asli_epg)] = id_asli_epg
                kamus_rumus_epg[rumus_samakan_teks(nama_epg)] = id_asli_epg
    except Exception as e:
        print(f"❌ Gagal EPG {url}: {e}")

daftar_teks_epg_dirumus = list(kamus_rumus_epg.keys())

print("2. Memproses M3U...")
try:
    m3u_resp = requests.get(M3U_URL, timeout=30)
    m3u_lines = m3u_resp.text.splitlines()
    
    m3u_baru = []
    log_sukses = []
    
    for line in m3u_lines:
        if line.startswith("#EXTINF"):
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            id_m3u = tvg_id_match.group(1).strip() if tvg_id_match else ""
            nama_m3u = line.split(',')[-1].strip()
            
            # A. Cek Prioritas 1: Kamus Manual
            kunci_manual = id_m3u.lower() if id_m3u.lower() in kamus_manual else nama_m3u.lower()
            
            if kunci_manual in kamus_manual:
                aturan = kamus_manual[kunci_manual]
                id_epg_terpilih = aturan["epg"]
                nama_rapi_epg = aturan["nama"]
                metode = "KAMUS MANUAL"
            else:
                # B. Cek Prioritas 2: Rumus Otomatis & Fuzzy
                id_epg_terpilih = ""
                nama_rapi_epg = ""
                metode = ""
                
                teks_m3u_dirumus = rumus_samakan_teks(id_m3u) if id_m3u else rumus_samakan_teks(nama_m3u)
                if not teks_m3u_dirumus: teks_m3u_dirumus = rumus_samakan_teks(nama_m3u)
                
                if teks_m3u_dirumus in kamus_rumus_epg:
                    id_epg_terpilih = kamus_rumus_epg[teks_m3u_dirumus]
                    nama_rapi_epg = epg_dict[id_epg_terpilih]
                    metode = "RUMUS EXACT"
                else:
                    mirip = difflib.get_close_matches(teks_m3u_dirumus, daftar_teks_epg_dirumus, n=1, cutoff=0.8)
                    if mirip:
                        id_epg_terpilih = kamus_rumus_epg[mirip[0]]
                        nama_rapi_epg = epg_dict[id_epg_terpilih]
                        metode = "RUMUS FUZZY"
            
            # Eksekusi Perubahan Baris M3U
            if id_epg_terpilih:
                line_bersih = re.sub(r' tvg-id="[^"]*"', '', line)
                line_baru = line_bersih.replace('#EXTINF:-1', f'#EXTINF:-1 tvg-id="{id_epg_terpilih}"')
                
                bagian = line_baru.split(',')
                bagian[-1] = nama_rapi_epg
                line_final = ','.join(bagian)
                
                m3u_baru.append(line_final)
                log_sukses.append(f"✅ [{metode}] {nama_m3u} -> ID: {id_epg_terpilih} | Nama: {nama_rapi_epg}")
            else:
                m3u_baru.append(line)
                log_sukses.append(f"❌ KOSONG: {nama_m3u} -> Tidak menemukan kecocokan")
        else:
            m3u_baru.append(line)

    with open("playlist_termapping.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_baru))
        
    with open("laporan_rumus.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_sukses))
        
    print("Selesai! File berhasil disimpan.")

except Exception as e:
    print(f"Error: {e}")
import re
import difflib
from io import BytesIO

# 1. URL M3U dan EPG
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml".
    
]

# 2. RUMUS OTOMATIS: Fungsi untuk menyamakan format teks
def rumus_samakan_teks(teks):
    if not teks: return ""
    teks = teks.lower()
    # Hapus kata-kata umum (sports, tv, hd, dll)
    teks = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network)\b', '', teks)
    # Hapus embel-embel dalam kurung/kurung siku
    teks = re.sub(r'\[.*?\]|\(.*?\)', '', teks)
    # Hapus SEMUA tanda baca (titik, spasi, strip) dan sisakan huruf/angka saja
    teks = re.sub(r'[^a-z0-9]', '', teks)
    return teks

print("1. Mengunduh dan memproses data EPG...")
epg_dict = {} # Menyimpan ID Asli EPG
kamus_rumus_epg = {} # Menyimpan Teks yang sudah dirumus -> ID Asli EPG

# HEADER PENYAMARAN AGAR TIDAK DIBLOKIR SERVER (Bypass bot protection)
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
}

for url in EPG_URLS:
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        
        # Cek apakah diblokir dan malah dikasih halaman web HTML (bukan XML/GZ)
        if b'<html' in resp.content[:20].lower() or b'<!doctype' in resp.content[:20].lower():
            print(f"⚠️ SKIP: Link {url} memblokir akses dan mengembalikan halaman web.")
            continue
            
        # Ekstrak konten
        if url.endswith('.gz'):
            content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read()
        else:
            content = resp.content
            
        root = ET.fromstring(content)
        for ch in root.findall('channel'):
            id_asli_epg = ch.get('id')
            display = ch.find('display-name')
            nama_epg = display.text if display is not None and display.text else id_asli_epg
            
            if id_asli_epg:
                epg_dict[id_asli_epg] = nama_epg
                # Masukkan ke kamus rumus (ID dan Nama EPG dirumus semua)
                kamus_rumus_epg[rumus_samakan_teks(id_asli_epg)] = id_asli_epg
                kamus_rumus_epg[rumus_samakan_teks(nama_epg)] = id_asli_epg
    except Exception as e:
        print(f"❌ Gagal memproses EPG {url}: {e}")

daftar_teks_epg_dirumus = list(kamus_rumus_epg.keys())

print("2. Memproses M3U dengan Rumus Otomatis...")
try:
    m3u_resp = requests.get(M3U_URL, timeout=30)
    m3u_lines = m3u_resp.text.splitlines()
    
    m3u_baru = []
    log_sukses = []
    
    for line in m3u_lines:
        if line.startswith("#EXTINF"):
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            id_m3u = tvg_id_match.group(1).strip() if tvg_id_match else ""
            nama_m3u = line.split(',')[-1].strip()
            
            # Terapkan rumus ke nama di M3U
            teks_m3u_dirumus = rumus_samakan_teks(id_m3u) if id_m3u else rumus_samakan_teks(nama_m3u)
            if not teks_m3u_dirumus: teks_m3u_dirumus = rumus_samakan_teks(nama_m3u)
            
            id_epg_terpilih = ""
            
            # 1. Cek Exact/Clean Match ke dalam kamus rumus
            if teks_m3u_dirumus in kamus_rumus_epg:
                id_epg_terpilih = kamus_rumus_epg[teks_m3u_dirumus]
            else:
                # 2. Jika masih meleset, gunakan tebakan akurasi 80% (Fuzzy)
                mirip = difflib.get_close_matches(teks_m3u_dirumus, daftar_teks_epg_dirumus, n=1, cutoff=0.8)
                if mirip:
                    id_epg_terpilih = kamus_rumus_epg[mirip[0]]
            
            # Proses penulisan ulang baris M3U
            if id_epg_terpilih:
                # Bersihkan tvg-id lama
                line_bersih = re.sub(r' tvg-id="[^"]*"', '', line)
                # Masukkan tvg-id yang sudah pasti cocok
                line_baru = line_bersih.replace('#EXTINF:-1', f'#EXTINF:-1 tvg-id="{id_epg_terpilih}"')
                
                # Ganti nama di layar agar rapi mengikuti EPG
                nama_rapi_epg = epg_dict[id_epg_terpilih]
                bagian = line_baru.split(',')
                bagian[-1] = nama_rapi_epg
                line_final = ','.join(bagian)
                
                m3u_baru.append(line_final)
                log_sukses.append(f"✅ KETEMU: {nama_m3u} -> otomatis pakai ID: {id_epg_terpilih} (Nama Layar: {nama_rapi_epg})")
            else:
                m3u_baru.append(line)
                log_sukses.append(f"❌ KOSONG: {nama_m3u} -> Tidak menemukan rumus yang cocok di EPG")
        else:
            m3u_baru.append(line)

    # 3. Simpan File Hasil
    with open("playlist_termapping.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_baru))
        
    with open("laporan_rumus.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_sukses))
        
    print("Selesai! Mapping otomatis dengan rumus berhasil. File telah disimpan.")

except Exception as e:
    print(f"Error: {e}")
