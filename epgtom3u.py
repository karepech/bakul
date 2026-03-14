import requests, re, gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. KONFIGURASI SUMBER M3U & EPG
# ==========================================
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"
]

# 3 Sumber M3U Karepech
MASTER_SOURCES = [
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u",    # (1)
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u",     # (2)
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/indonesia_combined.m3u"  # (3)
]

OUTPUT_FILE = "live_matches_only.m3u"
M3U_HEADER = '#EXTM3U url-tvg="https://www.open-epg.com/generate/bXxbrwUThe.xml" name="🔴 BAKUL WIFI SPORTS"'

# ==========================================
# 2. MESIN FILTER (HANYA CHANNEL OLAHRAGA)
# ==========================================
def normalisasi(n):
    n = n.lower().strip()
    n = re.sub(r'\b(?:champions?\s*tv|ctv)\s*(\d+)\b', r'champions tv \1', n)
    n = re.sub(r'\bsports?\s+stars?\b', 'sportstars', re.sub(r'\bspo\s+tv\b', 'spotv', n))
    n = re.sub(r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq)\b', '', n).strip()
    return n

def get_flag(n):
    n = n.lower()
    if any(x in n for x in [' au', 'aus', 'optus']): return "🇦🇺"
    if any(x in n for x in [' my', 'malaysia', 'astro']): return "🇲🇾"
    if any(x in n for x in [' sg', 'singapore', 'hub']): return "🇸🇬"
    if any(x in n for x in [' th', 'thai']): return "🇹🇭"
    if any(x in n for x in [' uk', 'english']): return "🇬🇧"
    if any(x in n for x in [' ar', 'mena', 'arab', 'premium']): return "🇸🇦"
    return "🇮🇩"

def is_sports_channel(name):
    n = name.lower()
    
    # 1. Aturan Khusus Astro (Filter ketat TV Berita/Religi)
    if 'astro' in n:
        haram = ['awani','ria','oasis','prima','rania','citra','hijrah','ceria','warna','shiq','vellithirai','vinmeen','box office']
        if any(x in n for x in haram): return False
        halal_astro = ['arena', 'supersport', 'grandstand', 'premier', 'cricket', 'badminton', 'football', 'golf', 'tennis', 'rugby', 'sport']
        if not any(x in n for x in halal_astro): return False
        return True

    # 2. Aturan Global (Wajib mengandung kata olahraga)
    sports_keywords = [
        'bein', 'spotv', 'sport', 'soccer', 'champions', 'espn', 'arena bola', 
        'golf', 'tennis', 'motor', 'fight', 'wwe', 'tnt', 'sky', 'optus', 'hub', 'mola', 'vidio'
    ]
    if any(x in n for x in sports_keywords):
        return True
        
    return False

# ==========================================
# 3. PROSES EKSEKUSI (REAL-TIME GUIDE)
# ==========================================
def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_chans, epg_logos, current_events = {}, {}, {}
    
    ses = requests.Session()
    ses.headers.update({'User-Agent': 'Mozilla/5.0'})

    print("Step 1: Sedot EPG (Mencari acara saat ini)...")
    for url in EPG_URLS:
        try:
            r = ses.get(url, timeout=60).content
            root = ET.fromstring(gzip.decompress(r) if r[:2] == b'\x1f\x8b' else r)
            
            for ch in root.findall("channel"):
                cid, cn = ch.get("id"), ch.findtext("display-name")
                if cid and cn: 
                    epg_chans[cid] = cn.strip()
                    icon = ch.find("icon")
                    if icon is not None: epg_logos[cid] = icon.get("src")
                    
            for pg in root.findall("programme"):
                cid = pg.get("channel")
                if cid not in epg_chans: continue
                
                # Cek Waktu (Hanya simpan acara yang SEDANG TAYANG detik ini)
                st = datetime.strptime(pg.get("start")[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
                sp = datetime.strptime(pg.get("stop")[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
                
                # Toleransi 5 menit mundur agar tidak hilang saat pergantian acara
                if (st - timedelta(minutes=5)) <= now_wib < sp:
                    title = pg.findtext("title") or ""
                    clean_title = re.sub(r'(?i)(\(l\)|\[l\]|live|langsung)', '', title).strip()
                    
                    current_events[cid] = {
                        "title": clean_title,
                        "start": st,
                        "stop": sp,
                        "logo": pg.find("icon").get("src") if pg.find("icon") is not None else ""
                    }
        except Exception as e:
            print(f"Gagal EPG {url}: {e}")
            continue

    print("Step 2: Sedot M3U Karepech & Sinkronisasi...")
    hasil_m3u = []
    url_tracker = set() # Anti-Spam Link
    
    for idx, url in enumerate(MASTER_SOURCES, 1):
        try:
            lines = ses.get(url, timeout=30).text.splitlines()
            block = []
            for ln in lines:
                if not ln.strip() or "EXTM3U" in ln.upper(): continue
                if ln.startswith("#"): 
                    block.append(ln)
                else:
                    stream_url = ln.strip()
                    extinf = next((t for t in block if "EXTINF" in t.upper()), None)
                    
                    if extinf and "," in extinf:
                        raw_attrs, m3u_name = extinf.split(",", 1)
                        m3u_name = m3u_name.strip()
                        
                        # 1. Pastikan ini Channel Olahraga
                        if not is_sports_channel(m3u_name):
                            block = []
                            continue
                            
                        # 2. Gembok Anti-Spam URL (Kalau URL video sama, buang)
                        if stream_url in url_tracker:
                            block = []
                            continue
                        url_tracker.add(stream_url)
                        
                        # 3. Bersihkan atribut bawaan
                        clean_attr = re.sub(r'\s*(group-title|tvg-id|tvg-name|tvg-logo)="[^"]+"', '', raw_attrs).strip()
                        flag = get_flag(m3u_name)
                        
                        # 4. Cari jadwal di EPG (Real-Time Matching)
                        matched_cid = None
                        n_m3u = normalisasi(m3u_name)
                        
                        for cid, ename in epg_chans.items():
                            n_epg = normalisasi(ename)
                            # Cek KTP (Region) - Deteksi nama murni tanpa HD/FHD
                            if n_epg == n_m3u or (n_epg in n_m3u and len(n_epg) > 4):
                                matched_cid = cid
                                break
                        
                        # 5. Eksekusi Tampilan TiviMate
                        if matched_cid and matched_cid in current_events:
                            # ADA JADWAL SAAT INI
                            ev = current_events[matched_cid]
                            jam = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')} WIB"
                            logo = ev['logo'] or epg_logos.get(matched_cid, "")
                            
                            judul = f"{flag} 🔴 {jam} - {ev['title']} [{m3u_name}] ({idx})"
                            baris_ext = f'{clean_attr} group-title="🔴 SPORTS SEDANG TAYANG" tvg-id="{matched_cid}" tvg-logo="{logo}", {judul}'
                        else:
                            # TIDAK ADA JADWAL (EPG Kosong/Error, tapi channel tetap dimasukkan!)
                            logo = epg_logos.get(matched_cid, "") if matched_cid else ""
                            judul = f"{flag} 🔴 Acara Tidak Diketahui [{m3u_name}] ({idx})"
                            # Tetap dikasih ID jika ketemu, agar logo bisa muncul
                            id_tag = f'tvg-id="{matched_cid}"' if matched_cid else 'tvg-id=""'
                            baris_ext = f'{clean_attr} group-title="🔴 SPORTS SEDANG TAYANG" {id_tag} tvg-logo="{logo}", {judul}'
                        
                        hasil_m3u.append([baris_ext, stream_url])
                        
                    block = []
        except Exception as e:
            print(f"Gagal M3U {url}: {e}")
            continue

    print("Step 3: Simpan Hasil Akhir...")
    # Urutkan abjad berdasarkan nama channel agar rapi
    hasil_m3u.sort(key=lambda x: x[0].split(',')[-1].lower())
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(M3U_HEADER + '\n')
        if not hasil_m3u: 
            f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA CHANNEL\nhttps://bwifi.my.id/live.mp4\n')
        for item in hasil_m3u: 
            f.write("\n".join(item) + "\n")

if __name__ == "__main__": main()
