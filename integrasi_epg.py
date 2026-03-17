import urllib.request
import os

def integrasi_epg():
    url_map = "https://raw.githubusercontent.com/karepech/bakul/refs/heads/main/map.txt"
    url_epg = "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/daftar_semua_sports_epg.txt"
    
    print("Mengunduh data map dan EPG...")
    try:
        data_map = urllib.request.urlopen(url_map).read().decode('utf-8').splitlines()
        data_epg = urllib.request.urlopen(url_epg).read().decode('utf-8').splitlines()
    except Exception as e:
        print(f"Gagal mengambil data: {e}")
        return

    master_map = {}
    
    # 1. Parsing map.txt
    for line in data_map:
        if "=" in line:
            parts = [p.strip() for p in line.split("=")]
            standar_nama = parts[0]
            master_map[standar_nama] = parts
        else:
            if line.strip():
                master_map[line.strip()] = [line.strip()]

    # 2. Cocokkan dengan daftar EPG
    for ch_epg in data_epg:
        ch_epg = ch_epg.strip()
        if not ch_epg: continue
        
        for standar_nama, variasi in master_map.items():
            if any(v.lower() in ch_epg.lower() or ch_epg.lower() in v.lower() for v in variasi):
                if ch_epg not in variasi:
                    variasi.append(ch_epg)
                break

    # 3. Simpan hasil ke file baru
    output_file = "hasil_mapping_epg.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for standar_nama, variasi in master_map.items():
            baris_baru = " = ".join(variasi)
            f.write(baris_baru + "\n")
            
    print(f"Selesai! Hasil disimpan di {output_file}")

if __name__ == "__main__":
    integrasi_epg()
