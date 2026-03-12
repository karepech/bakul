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
# OPTIMASI REGEX (LEBIH CEPAT & ANTI-JEBAKAN)
# ==========================================
REGEX_CHAMPIONS = re.compile(r'\b(?:champions?\s*tv|champions?|ctv)\s*(\d+)\b')
REGEX_STARS = re.compile(r'\bsports?\s+stars?\b')
REGEX_MNC = re.compile(r'\bmnc\s*sports?\b')
REGEX_SPO = re.compile(r'\bspo\s+tv\b')
REGEX_CYRILLIC_CJK = re.compile(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]')
REGEX_KUALITAS = re.compile(r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|id|my|sg|network)\b')
REGEX_NUMBERS = re.compile(r'\d+')
REGEX_WORDS = re.compile(r'[a-z0-9]+')
REGEX_JUDUL_1 = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_JUDUL_2 = re.compile(r'\s+')
REGEX_JUDUL_3 = re.compile(r'^[\-\:\,\|]\s*')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_VS = re.compile(r'\b(vs|v)\b')

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
    
    if 'bein' in n and not any(x in n for x in [' en', ' hk', ' th', ' ph', ' my', ' sg', ' au']): return "🇮🇩"
    if any(x in n for x in [' id', 'indo', 'vidio', 'rcti', 'sctv', 'mnc', 'tvri', 'antv', 'indosiar', 'rtv', 'inews']): return "🇮🇩"
    return "📺" 

def normalisasi_alias(name):
    n = name.lower().strip()
    n = REGEX_CHAMPIONS.sub(r'champions tv \1', n)
    n = REGEX_STARS.sub('sportstars', n) 
    n = REGEX_MNC.sub('sportstars', n)    
    n = REGEX_SPO.sub('spotv', n)              
    return n

def is_allowed_sport(title, ch_name):
    if not title: return False
    t = title.lower()
    c = normalisasi_alias(ch_name)
    
    if REGEX_CYRILLIC_CJK.search(t): return False

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
    # SENSOR KETAT HARAM
    if re.search(r'\b(?:' + '|'.join(haram) + r')\b', t): return False

    bola_channels = ['arena bola', 'football', 'soccer', 'premier', 'laliga']
    if any(x in c for x in bola_channels):
        if any(x in t for x in ['badminton', 'bwf', 'motogp', 'f1', 'basket', 'tennis']): return False
    
    # SENSOR KETAT HALAL (Menghapus kata jebakan seperti 'city', 'bri', 'open', 'live')
    halal = [
        "liga", "premier", "champions", "fa cup", "serie a", "bundesliga", "ligue 1", "dutch", "eredivisie",
        "manchester city", "manchester united", "madrid", "barcelona", "chelsea", "arsenal", "liverpool", "juventus", "milan", "inter", "bayern", "psg", 
        "indonesia", "bri liga 1", "sea games", "asean games", "soccer", "football", "copa", "piala", "fifa", "uefa", "mls", "afc", "aff",
        "badminton", "bwf", "all england", "thomas", "uber", "sudirman", "yonex", "swiss open", "china open", "china masters", "macau open", "indonesia masters",
        "voli", "volley", "vnl", "proliga", "futsal",
        "motogp", "moto2", "moto3", "f1", "formula", "grand prix", "racing", "sprint"
    ]
    
    # Deteksi batas kata murni agar "Brian" tidak dianggap "bri"
    if re.search(r'\b(?:' + '|'.join(halal).replace('+', r'\+') + r')\b', t) or REGEX_VS.search(t):
        return True
        
    return False

def is_match_akurat(epg_name, m3u_name):
    if not epg_name or not m3u_name: return False
    e = normalisasi_alias(epg_name)
    m = normalisasi_alias(m3u_name)
    e_clean = REGEX_KUALITAS.sub('', e).strip()
    m_clean = REGEX_KUALITAS.sub('', m).strip()
    num_e = REGEX_NUMBERS.findall(e_clean)
    num_m = REGEX_NUMBERS.findall(m_clean)
    ne = num_e[0] if num_e else '1'
    nm = num_m[0] if num_m else '1'
    if ne != nm: return False

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

    e_words = set(REGEX_WORDS.findall(e_clean))
    m_words = set(REGEX_WORDS.findall(m_clean))
    if e_words and m_words:
        if e_words.issubset(m_words) or m_words.issubset(e_words): return True
    return False

def parse_epg_time(time_str):
    if not time_str: return None
    try:
        if len(time_str) >= 20 and ('+' in time_str or '-' in time_str):
            dt = datetime.strptime(time_str[:20], "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        else:
            return datetime.strptime(time_str[:14], "%Y%m%d%H%M%S") + timedelta(hours=7) 
    except Exception:
        return None

def bersihkan_judul_event(title):
    bersih = REGEX_JUDUL_1.sub('', title)
    bersih = REGEX_JUDUL_2.sub(' ', bersih).strip()
    return REGEX_JUDUL_3.sub('', bersih)

# ==========================================================
# FILTER WAKTU SUPER PRESISI (REQUEST VVIP)
# ==========================================================
def is_valid_time(start_dt, title, ch_name):
    w = start_dt.hour + (start_dt.minute / 60.0) # Konversi ke desimal (contoh 18:30 = 18.5)
    t = title.lower()

    # 1. ATURAN BADMINTON (Full 24 Jam)
    is_badminton = any(k in t for k in ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'yonex', 'swiss open', 'china open', 'china masters', 'macau open'])
    if is_badminton: return True

    # 2. ATURAN BOLA VOLI
    is_voli = any(k in t for k in ['voli', 'volley', 'vnl', 'proliga'])
    if is_voli:
        # Asia: 12:00 - 20:00 || Eropa: 22:00 - 04:00 || Amerika: 05:00 - 11:00
        if (12.0 <= w <= 20.0) or (w >= 22.0 or w <= 4.0) or (5.0 <= w <= 11.0):
            return True
        return False

    # 3. ATURAN MOTOGP & F1 (Racing)
    is_racing = any(k in t for k in ['motogp', 'moto2', 'moto3', 'f1', 'formula', 'grand prix', 'sprint'])
    if is_racing:
        # Amerika: 03:00-06:00 || Aus/Jpn: 09:00-13:00 || Asia: 13:00-16:00 || Eropa: 18:00-22:00
        if (3.0 <= w <= 6.0) or (9.0 <= w <= 16.0) or (18.0 <= w <= 22.0):
            return True
        return False

    # 4. ATURAN LIGA SEPAK BOLA & LAINNYA BERDASARKAN BENUA
    # EROPA (18:30 - 03:00)
    eropa_keywords = ['premier', 'champions', 'serie a', 'la liga', 'bundesliga', 'ligue 1', 'fa cup', 'eredivisie', 'uefa', 'euro', 'england', 'italy', 'spain', 'germany', 'carabao', 'copa del rey']
    if any(k in t for k in eropa_keywords):
        if w >= 18.5 or w <= 3.0: return True
        return False 

    # AMERIKA (06:00 - 11:00)
    amerika_keywords = ['mls', 'concacaf', 'libertadores', 'sudamericana', 'ncaa', 'liga mx', 'america', 'usl', 'argentina', 'brasil', 'nba', 'nfl', 'conmebol']
    if any(k in t for k in amerika_keywords):
        if 6.0 <= w <= 11.0: return True
        return False 

    # ASIA LOKAL (15:00 - 21:00)
    asia_keywords = ['j-league', 'j1', 'j2', 'j3', 'k-league', 'a-league', 'australia', 'japan', 'korea', 'afc', 'asian', 'aff', 'liga 1', 'bri liga', 'indonesia', 'shopee', 'timnas', 'persib', 'persija', 'persebaya', 'piala presiden', 'liga 2']
    if any(k in t for k in asia_keywords):
        if 15.0 <= w <= 21.0: return True
        return False 

    # 5. PENYAPU RANJAU (Fallback Umum jika liganya tidak spesifik)
    # Blokir keras siang hari (03:00 Pagi sampai 15:00 Sore) untuk acara yang tidak jelas asal-usulnya
    if 3.0 < w < 15.0:
        return False

    return True

# ==========================================
# III. MAIN EKSEKUSI (INTI SCRIPT)
# ==========================================

def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    epg_channels = {}
    epg_channel_logos = {} 
    jadwal_per_channel = {}

    ALL_EPG_URLS = EPG_URLS.copy()
    for u in GLOBAL_EPG_URL.split(','):
        if u.strip() and u.strip() not in ALL_EPG_URLS:
            ALL_EPG_URLS.append(u.strip())

    if now_wib.hour < 5:
        batas_waktu_upcoming = (now_wib + timedelta(days=2)).replace(hour=5, minute=0, second=0, microsecond=0)
    else:
        batas_waktu_upcoming = (now_wib + timedelta(days=3)).replace(hour=5, minute=0, second=0, microsecond=0)

    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    print(f"Step 1: Mengunduh dan memproses {len(ALL_EPG_URLS)} EPG...")
    for url in ALL_EPG_URLS:
        if not url: continue
        try:
            r_epg = session.get(url, timeout=60)
            if r_epg.status_code != 200: continue
                
            content = r_epg.content
            if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                content = gzip.decompress(content)
                
            root = ET.fromstring(content)
            
            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                ch_name = ch.findtext("display-name")
                icon_node = ch.find("icon")
                ch_logo = icon_node.get("src") if icon_node is not None else ""
                
                if ch_id and ch_name:
                    epg_channels[ch_id] = ch_name.strip()
                    if ch_logo: epg_channel_logos[ch_id] = ch_logo.strip()
                        
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

                # TERAPKAN ATURAN WAKTU PRESISI DISINI
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

        except Exception:
            continue

    print("Step 2: Menggabungkan file Multi M3U master Anda...")
    m3u_lines = []
    for url in M3U_URLS:
        if not url: continue
        print(f" -> Sedot M3U: {url.split('/')[-1]} ...")
        try:
            r_m3u = session.get(url, timeout=30)
            if r_m3u.status_code == 200:
                m3u_lines.extend(r_m3u.text.splitlines())
        except Exception:
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
                    clean_attrs = REGEX_JUDUL_2.sub(' ', clean_attrs).strip()

                    bendera = get_flag(nama_asli_m3u)

                    for ch_id, nama_epg in epg_channels.items():
                        if is_match_akurat(nama_epg, nama_asli_m3u):
                            if ch_id in jadwal_per_channel:
                                for event in jadwal_per_channel[ch_id]:
                                    jam_mulai = event["start_dt"].strftime('%H:%M')
                                    jam_selesai = event["stop_dt"].strftime('%H:%M')
                                    jam_str = f"{jam_mulai}-{jam_selesai} WIB"
                                    
                                    logo_epg_prog = event["prog_logo"]
                                    logo_epg_chan = epg_channel_logos.get(ch_id, "")
                                    logo_final = logo_epg_prog or logo_epg_chan or logo_asli
                                    
                                    if event["is_live"]:
                                        grup_baru = "🔴 ACARA SEDANG TAYANG"
                                        judul_akhir = f"{bendera} 🔴 {jam_str} - {event['title_display']} [{nama_asli_m3u}]"
                                        stream_final = stream_url 
                                        order = 0 
                                        
                                        baris_extinf = f'{clean_attrs} group-title="{grup_baru}" tvg-id="{ch_id}" tvg-name="{nama_epg}" tvg-logo="{logo_final}", {judul_akhir}'
                                        block_final = [baris_extinf if t.upper().startswith("#EXTINF") else t for t in channel_block if not t.upper().startswith("#EXTGRP")]
                                        
                                        hasil_akhir.append({"kategori_order": order, "start_time": event["start_dt"].timestamp(), "title_sort": event['title_display'], "baris_lengkap": block_final + [stream_final]})
                                        
                                    else:
                                        grup_baru = "📅 ACARA AKAN DATANG"
                                        hari_ini = now_wib.date()
                                        besok = hari_ini + timedelta(days=1)
                                        lusa = hari_ini + timedelta(days=2)
                                        event_date = event["start_dt"].date()
                                        
                                        kunci_backup = f"{ch_id}_{event['start_dt'].strftime('%Y%m%d%H%M')}"
                                        t_norm = REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', event['title_display'].lower()))
                                        kunci_acara = f"{event['start_dt'].strftime('%Y%m%d%H%M')}_{t_norm}"
                                        
                                        if kunci_backup in upcoming_tracker_backup or kunci_acara in upcoming_tracker_acara: continue 
                                            
                                        upcoming_tracker_backup.add(kunci_backup)
                                        upcoming_tracker_acara.add(kunci_acara)

                                        if event_date == hari_ini: judul_akhir = f"{bendera} ⏳ {jam_str} - {event['title_display']}"
                                        elif event_date == besok: judul_akhir = f"{bendera} ⏳ Besok {jam_str} - {event['title_display']}"
                                        elif event_date == lusa: judul_akhir = f"{bendera} ⏳ Lusa {jam_str} - {event['title_display']}"
                                        else: judul_akhir = f"{bendera} ⏳ {event['start_dt'].strftime('%d/%m')} {jam_str} - {event['title_display']}"

                                        stream_final = LINK_UPCOMING 
                                        order = 1 
                                        
                                        baris_extinf = f'{clean_attrs} group-title="{grup_baru}" tvg-id="{ch_id}" tvg-name="{nama_epg}" tvg-logo="{logo_final}", {judul_akhir}'
                                        block_final = [baris_extinf if t.upper().startswith("#EXTINF") else t for t in channel_block if not t.upper().startswith("#EXTGRP")]

                                        hasil_akhir.append({"kategori_order": order, "start_time": event["start_dt"].timestamp(), "title_sort": event['title_display'], "baris_lengkap": block_final + [stream_final]})
            channel_block = []

    print("Step 4: Mengurutkan dan menyimpan hasil...")
    hasil_akhir.sort(key=lambda x: (x["kategori_order"], x["start_time"], x["title_sort"]))

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(f'#EXTM3U url-tvg="{GLOBAL_EPG_URL}" name="🔴 OLAHRAGA AKTIF VIP"\n')
            if not hasil_akhir:
                f.write('#EXTINF:-1 group-title="ℹ️ INFORMASI", ℹ️ BELUM ADA JADWAL HARI INI\n')
                f.write(f'{LINK_STANDBY}\n')
            for item in hasil_akhir:
                for baris_hasil in item["baris_lengkap"]:
                    f.write(baris_hasil + "\n")
        print(f"Sukses! Playlist tersimpan di {OUTPUT_FILE} dengan {len(hasil_akhir)} pertandingan.")
    except Exception as e:
        print(f"Gagal menyimpan file: {e}")

if __name__ == "__main__":
    main()
