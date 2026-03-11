import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone
import gzip
import io

# ==========================================
# I. KONFIGURASI EMAS (MULTI-EPG & M3U VIP)
# ==========================================

EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"                   
]

M3U_URLS = [
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/indonesia_combined.m3u"
]

GLOBAL_EPG_URL = "https://www.open-epg.com/generate/bXxbrwUThe.xml,https://i.mjh.nz/SamsungTVPlus/all.xml,https://i.mjh.nz/au/all/epg.xml,https://www.tdtchannels.com/epg/TV.xml,https://www.open-epg.com/files/indonesia2.xml,https://www.open-epg.com/files/indonesia6.xml,https://www.open-epg.com/files/thailand.xml,https://www.open-epg.com/files/thailandpremium.xml,https://i.mjh.nz/PlutoTV/all.xml,https://www.open-epg.com/files/francepremium.xml,https://avkb.short.gy/tsepg.xml.gz,https://raw.githubusercontent.com/dbghelp/mewatch-EPG/refs/heads/main/mewatch.xml,https://epg1.168.us.kg/mytvsuper.com.xml"

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

# ==========================================
# II. FUNGSI PEMBANTU (FILTRASI & LOGIKA)
# ==========================================

def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'astro', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    
    if 'bein' in n and not any(x in n for x in [' en', ' hk', ' th', ' ph', ' my', ' sg', ' au']): 
        return "🇮🇩"
    if any(x in n for x in [' id', 'indo', 'vidio']): return "🇮🇩"
    
    return "📺" 

def is_allowed_sport(title, ch_name):
    if not title: return False
    t = title.lower()
    c = ch_name.lower()
    
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', title): return False

    haram = [
        "(d)", "[d]", "(r)", "[r]", "delay", "replay", "re-run", "siaran ulang", "recorded", "archives", 
        "tunda", "tayangan ulang", "rekap", "ulangan", "rakaman", "cuplikan",
        "news", "studio", "pre-match", "post-match", "update", "talk", "show", "weekly", 
        "magazine", "highlight", "classic", "review", "encore", "tba", "hl", "dl", "rev", "story",
        "fitness", "workout", "gym", "golden fit",
        "tennis", "wta", "atp", "wimbledon", "golf", "pga", "wwe", "ufc", "boxing", "fight", "mma", 
        "smackdown", "snooker", "darts", "rugby", "cricket", "icc", "mlb", "nhl", "nfl", "baseball", 
        "wbc", "basketball", "nba", "fiba", "movie", "special delivery", "billiard", "t20"
    ]
    if any(h in t for h in haram): return False

    bola_channels = ['arena bola', 'football', 'soccer', 'premier', 'laliga']
    if any(x in c for x in bola_channels):
        if any(x in t for x in ['badminton', 'bwf', 'motogp', 'f1', 'basket', 'tennis']):
            return False
    
    halal = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", "dutch", "eredivisie",
        "fc", "united", "city", "madrid", "barcelona", "chelsea", "arsenal", "liverpool",  "vs",  "indonesia",  "bri",  "sea games",  "asean games", 
        "juventus", "milan", "inter", "bayern", "psg", "soccer", "football", "copa", "piala",  "live",  "league", "fifa series",
        "afc", "aff", "fifa", "uefa", "mls", 
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", 
        "voli", "volley", "vnl", "proliga", "futsal", "yonex", "li-ning", "victor", "open",
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint"
    ]
    
    if any(h in t for h in halal) or ' vs ' in t or ' v ' in t:
        return True
        
    return False

def is_match_akurat(epg_name, m3u_name):
    if not epg_name or not m3u_name: return False
    e = epg_name.lower().strip()
    m = m3u_name.lower().strip()

    m = re.sub(r'\bctv\s*(\d+)', r'champions tv \1', m)
    e = re.sub(r'\bctv\s*(\d+)', r'champions tv \1', e)

    hapus_kualitas = r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|id|my|sg|network)\b'
    e_clean = re.sub(hapus_kualitas, '', e).strip()
    m_clean = re.sub(hapus_kualitas, '', m).strip()

    num_e = re.findall(r'\d+', e_clean)
    num_m = re.findall(r'\d+', m_clean)

    ne = num_e[0] if num_e else '1'
    nm = num_m[0] if num_m else '1'
    
    if ne != nm: 
        return False

    strict_nets = ['astro', 'bein', 'spotv', 'sportstars', 'soccer channel', 'fight', 'champions', 'hub']
    
    for net in strict_nets:
        if net in e_clean or net in m_clean:
            if (net in e_clean) != (net in m_clean): return False
            
            if net == 'astro':
                subs = ['arena bola 2', 'arena bola', 'arena', 'supersport 1', 'supersport 2', 'supersport 3', 'supersport 4', 'supersport 5', 'supersport', 'cricket', 'badminton', 'football', 'golf', 'grandstand', 'premier']
                found_e = next((s for s in subs if s in e_clean), 'none')
                found_m = next((s for s in subs if s in m_clean), 'none')
                if found_e != found_m: return False
            
            if net == 'bein':
                if ('xtra' in e_clean or 'extra' in e_clean) != ('xtra' in m_clean or 'extra' in m_clean): return False

            if net == 'spotv':
                if ('now' in e_clean) != ('now' in m_clean): return False

            return True

    e_words = set(re.findall(r'[a-z0-9]+', e_clean))
    m_words = set(re.findall(r'[a-z0-9]+', m_clean))
    
    if e_words and m_words:
        if e_words.issubset(m_words) or m_words.issubset(e_words):
            return True

    return False

def parse_epg_time(time_str):
    if not time_str: return None
    try:
        if len(time_str) >= 20 and ('+' in time_str or '-' in time_str):
            dt = datetime.strptime(time_str[:20], "%Y%m%d%H%M%S %z")
            dt_wib = dt.astimezone(timezone(timedelta(hours=7)))
            return dt_wib.replace(tzinfo=None)
        else:
            dt = datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
            return dt + timedelta(hours=7) 
    except Exception:
        return None

def bersihkan_judul_event(title):
    bersih = re.sub(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)', '', title)
    bersih = re.sub(r'\s+', ' ', bersih).strip()
    bersih = re.sub(r'^[\-\:\,\|]\s*', '', bersih)
    return bersih

# ==========================================================
# FITUR BARU: HUKUM BENUA (PEMBANTAI REPLAY BERDASARKAN JAM)
# ==========================================================
def is_valid_time(start_dt, title, ch_name):
    waktu_mulai = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()
    c = ch_name.lower()

    # 1. VIP PASS: OLAHRAGA GLOBAL 24 JAM
    non_bola = ['badminton', 'bwf', 'motogp', 'f1', 'formula', 'voli', 'volleyball', 'futsal', 'moto2', 'moto3', 'sprint', 'tennis']
    if any(k in t for k in non_bola): 
        return True

    # 2. VIP PASS: BOLA ASIA & AMERIKA (Sah tayang pagi/siang)
    bola_pagi_sah = [
        'mls', 'concacaf', 'libertadores', 'sudamericana', 'ncaa', 'liga mx', 'america', 'usl', 'argentina', 'brasil',
        'j-league', 'j1', 'j2', 'j3', 'k-league', 'a-league', 'australia', 'japan', 'korea',
        'afc', 'asian', 'liga 1', 'bri liga', 'indonesia', 'shopee', 'aff', 'timnas', 'persib', 'persija', 'persebaya'
    ]
    is_bola_pagi_sah = any(k in t or k in c for k in bola_pagi_sah)

    # 3. HUKUM EROPA & beIN SPORTS (Hanya Live jam 18:00 - 05:00 WIB)
    eropa_channels = ['bein', 'sky', 'tnt', 'movistar', 'dazn', 'rmc', 'canal+']
    if any(x in c for x in eropa_channels):
        if 5.0 <= waktu_mulai < 18.0:
            if not is_bola_pagi_sah:
                return False 
        return True

    # 4. HUKUM AMERIKA (Hanya Live jam 05:00 Pagi - 13:00 Siang WIB)
    amerika_channels = ['espn', 'fox', 'cbs', 'nbc', 'tyc', 'tudn']
    if any(x in c for x in amerika_channels):
        if 13.0 <= waktu_mulai < 24.0 or 0.0 <= waktu_mulai < 5.0:
            return False 
        return True

    # 5. HUKUM ASIA & LOKAL (Bebas 24 Jam)
    asia_channels = ['astro', 'spotv', 'champions', 'sportstars', 'soccer channel', 'rcti', 'sctv', 'indosiar']
    if any(x in c for x in asia_channels):
        return True 

    # 6. PENYAPU RANJAU (Sisa channel: Jika tayang siang tapi bukan bola pagi sah -> BUANG)
    if 5.0 <= waktu_mulai < 17.0:
        if not is_bola_pagi_sah:
            return False 

    return True

# ==========================================
# III. MAIN EKSEKUSI (INTI SCRIPT)
# ==========================================

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels = {}
    jadwal_per_channel = {}

    if now_wib.hour < 5:
        batas_waktu_upcoming = now_wib.replace(hour=5, minute=0, second=0, microsecond=0)
    else:
        batas_waktu_upcoming = (now_wib + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)

    print("Step 1: Mengunduh dan memproses Trio Emas EPG...")
    for url in EPG_URLS:
        if not url: continue
        try:
            r_epg = requests.get(url, timeout=120)
            if r_epg.status_code != 200: continue
                
            content = r_epg.content
            if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
                
            root = ET.fromstring(content)
            
            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                ch_name = ch.findtext("display-name")
                if ch_id and ch_name:
                    epg_channels[ch_id] = ch_name.strip()
                    
            for prog in root.findall("programme"):
                ch_id = prog.get("channel")
                if ch_id not in epg_channels: continue
                
                if prog.find("previously-shown") is not None: continue

                icon_node = prog.find("icon")
                epg_prog_logo = icon_node.get("src") if icon_node is not None else ""
                    
                ch_name = epg_channels[ch_id]
                title_raw = prog.findtext("title") or ""
                
                if not is_allowed_sport(title_raw, ch_name): continue
                    
                start_dt = parse_epg_time(prog.get("start"))
                stop_dt = parse_epg_time(prog.get("stop"))

                if not start_dt or not stop_dt or start_dt >= stop_dt: continue
                if stop_dt <= now_wib: continue 
                if start_dt >= batas_waktu_upcoming: continue

                # Terapkan HUKUM BENUA untuk memfilter jadwal!
                if not is_valid_time(start_dt, title_raw, ch_name): continue

                durasi_menit = (stop_dt - start_dt).total_seconds() / 60
                if durasi_menit < 30: continue 

                bola_keywords = ['liga', 'premier', 'champions', 'fa cup', 'serie a', 'bundesliga', 'ligue 1', 'bein', 'fc', 'united', 'vs', 'v']
                is_football = any(k in ch_name.lower() or k in title_raw.lower() for k in bola_keywords)
                if is_football and durasi_menit < 85: continue

                waktu_toleransi_live = start_dt - timedelta(minutes=5)
                is_live = waktu_toleransi_live <= now_wib < stop_dt

                judul_bersih = bersihkan_judul_event(title_raw)
                
                if ch_id not in jadwal_per_channel:
                    jadwal_per_channel[ch_id] = []
                
                jadwal_per_channel[ch_id].append({
                    "title_display": judul_bersih,
                    "start_dt": start_dt,
                    "stop_dt": stop_dt,
                    "is_live": is_live,
                    "prog_logo": epg_prog_logo 
                })

        except Exception as e:
            continue

    print("Step 2: Menggabungkan file Multi M3U master Anda...")
    m3u_lines = []
    for url in M3U_URLS:
        if not url: continue
        print(f" -> Sedot M3U: {url.split('/')[-1]} ...")
        try:
            r_m3u = requests.get(url, timeout=30)
            r_m3u.raise_for_status()
            m3u_lines.extend(r_m3u.text.splitlines())
        except Exception as e:
            continue

    print("Step 3: Meracik Playlist VIP Olahraga Aktif...")
    hasil_akhir = []
    channel_block = []
    upcoming_tracker_backup = set()
    upcoming_tracker_acara = set()

    for line in m3u_lines:
        baris = line.strip()
        if not baris: continue
        if baris.upper().startswith("#EXTM3U"): continue

        if baris.startswith("#"):
            channel_block.append(baris)
        else:
            stream_url = baris
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
                    
                    logo_asli_match = re.search(r'(?i)tvg-logo=(["\'])(.*?)\1', bagian_atribut)
                    logo_asli = logo_asli_match.group(2) if logo_asli_match else ""
                    
                    clean_attrs = bagian_atribut
                    attrs_to_remove = ['group-title', 'tvg-group', 'tvg-id', 'tvg-name', 'tvg-logo']
                    for attr in attrs_to_remove:
                        clean_attrs = re.sub(rf'(?i)\s*{attr}=(["\']).*?\1', '', clean_attrs)
                        clean_attrs = re.sub(rf'(?i)\s*{attr}=[^"\'\s,]+', '', clean_attrs)
                    clean_attrs = re.sub(r'\s+', ' ', clean_attrs).strip()

                    bendera = get_flag(nama_asli_m3u)

                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u):
                            if ch_id in jadwal_per_channel:
                                for event in jadwal_per_channel[ch_id]:
                                    jam_mulai = event["start_dt"].strftime('%H:%M')
                                    jam_selesai = event["stop_dt"].strftime('%H:%M')
                                    jam_str = f"{jam_mulai}-{jam_selesai} WIB"
                                    
                                    # PINJAM LOGO DARI M3U JIKA EPG GAK PUNYA POSTER (Fitur yg dipertahankan)
                                    logo_final = event["prog_logo"] if event["prog_logo"] else logo_asli
                                    
                                    if event["is_live"]:
                                        grup_baru = "🔴 ACARA SEDANG TAYANG"
                                        judul_akhir = f"{bendera} 🔴 {jam_str} - {event['title_display']} [{nama_asli_m3u}]"
                                        stream_final = stream_url 
                                        order = 0 
                                        
                                        baris_extinf = f'{clean_attrs} group-title="{grup_baru}" tvg-id="{ch_id}" tvg-name="{nama_epg}" tvg-logo="{logo_final}", {judul_akhir}'
                                        
                                        block_final = []
                                        for tag in channel_block:
                                            if tag.upper().startswith("#EXTINF"): block_final.append(baris_extinf)
                                            elif tag.upper().startswith("#EXTGRP"): pass 
                                            else: block_final.append(tag)
                                        
                                        hasil_akhir.append({
                                            "kategori_order": order,
                                            "start_time": event["start_dt"].timestamp(),
                                            "title_sort": event['title_display'],
                                            "baris_lengkap": block_final + [stream_final]
                                        })
                                        
                                    else:
                                        grup_baru = "📅 ACARA AKAN DATANG"
                                        if event["start_dt"].date() == now_wib.date():
                                            judul_akhir = f"{bendera} ⏳ {jam_str} - {event['title_display']}"
                                        else:
                                            judul_akhir = f"{bendera} ⏳ Besok {jam_str} - {event['title_display']}"
                                        stream_final = LINK_UPCOMING 
                                        order = 1 
                                        
                                        kunci_backup = f"{ch_id}_{event['start_dt'].strftime('%Y%m%d%H%M')}"
                                        t_norm = re.sub(r'[^a-z0-9]', '', re.sub(r'\b(vs|v)\b', '', event['title_display'].lower()))
                                        kunci_acara = f"{event['start_dt'].strftime('%Y%m%d%H%M')}_{t_norm}"
                                        
                                        if kunci_backup in upcoming_tracker_backup or kunci_acara in upcoming_tracker_acara:
                                            continue 
                                            
                                        upcoming_tracker_backup.add(kunci_backup)
                                        upcoming_tracker_acara.add(kunci_acara)
                                        
                                        baris_extinf = f'{clean_attrs} group-title="{grup_baru}" tvg-id="{ch_id}" tvg-name="{nama_epg}" tvg-logo="{logo_final}", {judul_akhir}'
                                        
                                        block_final = []
                                        for tag in channel_block:
                                            if tag.upper().startswith("#EXTINF"): block_final.append(baris_extinf)
                                            elif tag.upper().startswith("#EXTGRP"): pass 
                                            else: block_final.append(tag)
                                        
                                        hasil_akhir.append({
                                            "kategori_order": order,
                                            "start_time": event["start_dt"].timestamp(),
                                            "title_sort": event['title_display'],
                                            "baris_lengkap": block_final + [stream_final]
                                        })
            
            channel_block = [] 

    def sorting_logic(x):
        return (x["kategori_order"], x["start_time"], x["title_sort"])

    print("Step 4: Menyortir Berdasarkan Jam Tayang & Menyimpan File M3U Final...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f'#EXTM3U url-tvg="{GLOBAL_EPG_URL}" name="🔴 OLAHRAGA AKTIF VIP"\n')
        
        if not hasil_akhir:
            f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA JADWAL HARI INI\n')
            f.write(f'{LINK_STANDBY}\n')
        else:
            hasil_akhir.sort(key=sorting_logic)
            for item in hasil_akhir:
                for blk in item["baris_lengkap"]:
                    f.write(blk + "\n")

    print(f"\nSELESAI ✔ → {len(hasil_akhir)} link event premium berhasil diracik!")

if __name__ == "__main__":
    main()
