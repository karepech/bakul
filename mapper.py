import requests
import gzip
import xml.etree.ElementTree as ET
import re
from io import BytesIO

# URL M3U dan EPG
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"
]

epg_ids = set()

# 1. Kumpulkan semua ID dari ketiga file EPG
print("Mendownload dan mengekstrak data EPG...")
for url in EPG_URLS:
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Ekstrak jika formatnya .gz
        if url.endswith('.gz'):
            xml_content = gzip.GzipFile(fileobj=BytesIO(response.content)).read()
        else:
            xml_content = response.content
            
        root = ET.fromstring(xml_content)
        for channel in root.findall('channel'):
            channel_id = channel.get('id')
            if channel_id:
                epg_ids.add(channel_id)
    except Exception as e:
        print(f"Gagal memproses {url}: {e}")

# 2. Proses file M3U dan Cocokkan
print("Mendownload M3U dan mulai mencocokkan...")
try:
    m3u_response = requests.get(M3U_URL, timeout=30)
    m3u_response.raise_for_status()
    m3u_lines = m3u_response.text.splitlines()
    
    results = []
    for line in m3u_lines:
        if line.startswith("#EXTINF"):
            # Cari tvg-id
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            tvg_id = tvg_id_match.group(1).strip() if tvg_id_match else ""
            
            # Cari nama channel (teks setelah koma terakhir)
            channel_name = line.split(',')[-1].strip()
            
            # Logika penentuan ID yang akan dicek
            if tvg_id:
                check_id = tvg_id
                display_id = tvg_id
            else:
                check_id = channel_name
                display_id = f"{channel_name} (dari nama channel)"
            
            # Cek ke dalam daftar EPG gabungan
            if check_id in epg_ids:
                status = "✅ COCOK"
            else:
                status = "❌ KOSONG"
                
            results.append(f"{status} | ID: {display_id} | Nama TV: {channel_name}")
            
    # Tulis hasil ke file teks
    with open("hasil_mapping.txt", "w", encoding="utf-8") as f:
        f.write("=== LAPORAN MAPPING M3U KE EPG ===\n")
        f.write(f"Total ID EPG unik yang berhasil dikumpulkan: {len(epg_ids)}\n")
        f.write("==================================\n\n")
        f.write("\n".join(results))
        
    print("Selesai! Hasil disimpan di hasil_mapping.txt")
    
except Exception as e:
    print(f"Gagal memproses M3U: {e}")
