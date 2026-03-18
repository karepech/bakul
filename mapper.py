import requests
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
from io import BytesIO

# URL M3U dan EPG
M3U_URL = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"
]

# RUMUS OTOMATIS: Fungsi untuk menyamakan format teks
def rumus_samakan_teks(teks):
    if not teks: return ""
    teks = teks.lower()
    # 1. Hapus kata-kata umum (sports, tv, hd, dll)
    teks = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network)\b', '', teks)
    # 2. Hapus embel-embel dalam kurung/kurung siku
    teks = re.sub(r'\[.*?\]|\(.*?\)', '', teks)
    # 3. Hapus SEMUA tanda baca (titik, spasi, strip) dan sisakan huruf/angka saja
    teks = re.sub(r'[^a-z0-9]', '', teks)
    return teks

print("1. Mengunduh dan memproses data EPG...")
epg_dict = {} # Menyimpan ID Asli EPG
kamus_rumus_epg = {} # Menyimpan Teks yang sudah dirumus -> ID Asli EPG

for url in EPG_URLS:
    try:
        resp = requests.get(url, timeout=30)
        content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read() if url.endswith('.gz') else resp.content
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
        print(f"Gagal memproses EPG {url}: {e}")

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
            
            # Cek ke dalam kamus rumus
            if teks_m3u_dirumus in kamus_rumus_epg:
                id_epg_terpilih = kamus_rumus_epg[teks_m3u_dirumus]
            else:
                # Jika masih meleset, gunakan tebakan akurasi 80% (Fuzzy)
                mirip = difflib.get_close_matches(teks_m3u_dirumus, daftar_teks_epg_dirumus, n=1, cutoff=0.8)
                if mirip:
                    id_epg_terpilih = kamus_rumus_epg[mirip[0]]
            
            # Proses penulisan ulang baris M3U
            if id_epg_terpilih:
                # Bersihkan tvg-id lama
                line_bersih = re.sub(r' tvg-id="[^"]*"', '', line)
                # Masukkan tvg-id yang sudah pasti cocok
                line_baru = line_bersih.replace('#EXTINF:-1', f'#EXTINF:-1 tvg-id="{id_epg_terpilih}"')
                
                # Opsional: Jika ingin nama di layar ikut berubah jadi rapi sesuai EPG
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

    # Simpan File
    with open("playlist_termapping.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_baru))
        
    with open("laporan_rumus.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_sukses))
        
    print("Selesai! Mapping otomatis dengan rumus berhasil.")

except Exception as e:
    print(f"Error: {e}")
