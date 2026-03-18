import requests
import cloudscraper
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO

# ========================================================
# 1. KONFIGURASI URL UTAMA
# ========================================================
M3U_URLS = [
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u"
]
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://epg.pw/xmltv/epg.xml.gz"
]
OUTPUT_FILE = "playlist_termapping.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

GLOBAL_SEEN_STREAM_URLS = set()

# ========================================================
# 2. MESIN MAPPING CERDAS KITA (Kamus Manual & Rumus Fuzzy)
# ========================================================
def rumus_samakan_teks(teks):
    if not teks: return ""
    teks = teks.lower()
    teks = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network)\b', '', teks)
    teks = re.sub(r'\[.*?\]|\(.*?\)', '', teks)
    teks = re.sub(r'[^a-z0-9]', '', teks)
    return teks

kamus_manual = {}
if os.path.exists("kamus_mapping.txt"):
    with open("kamus_mapping.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                parts = line.strip().split("=")
                if len(parts) == 3:
                    kamus_manual[parts[1].strip().lower()] = {"epg": parts[0].strip(), "nama": parts[2].strip()}

# ========================================================
# 3. ATURAN FILTER SULTAN (Sesuai Skrip Anda)
# ========================================================
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    return re.sub(r'^[\-\:\,\|]\s*', '', re.sub(r'\s+', ' ', bersih)).strip()

def generate_event_key(title, timestamp):
    tc = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', title)
    tc = re.sub(r'\d+\]?$', '', tc.strip())
    return f"{REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', tc.lower()))}_{timestamp}"

def get_vip_score(ch_name):
    n = ch_name.lower()
    if any(k in n for k in ['bein', 'spotv', 'sportstars', 'soccer channel', 'champions tv', 'rcti sports', 'inews sports', 'mnc sports']): return 0
    return 1

def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' us', 'usa', 'america']): return "🇺🇸" 
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk', 'sky']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai', 'true']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    if any(x in n for x in [' ae', 'arab', 'mena', 'ssc', 'alkass', 'abu dhabi']): return "🇸🇦"
    if any(x in n for x in [' za', 'supersport', 'africa']): return "🇿🇦"
    if any(x in n for x in [' id', 'indo', 'indonesia', 'vidio', 'rcti', 'sctv', 'mnc', 'tvri', 'antv', 'indosiar', 'rtv', 'inews']): return "🇮🇩"
    if 'bein' in n and not any(x in n for x in [' us', ' sg', ' my', ' uk', ' th', ' hk', ' au', ' ae', ' za', ' ph']): return "🇮🇩"
    return "📺"

def is_allowed_sport(title, durasi_menit):
    t = title.lower()
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', t) or durasi_menit <= 30: return False
    haram_simbol = ["(d)", "[d]", "(r)", "[r]", "(c)", "[c]", "hls", "hl ", "h/l", "rev ", "rep ", "del "]
    if any(s in t for s in haram_simbol): return False
    haram_kata = ["replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary", "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", "sepak mula", "dokumenter", "obrolan", "bincang", "berita", "news", "apa kabar", "religi", "quran", "mekkah", "masterchef", "cgtn", "arirang", "cnn", "lfctv", "mutv", "chelsea tv", "re-live", "relive", "history", "retro", "memories", "greatest", "wwe", "ufc", "mma", "boxing", "fight", "fightesport", "esport", "e-sport", "smackdown", "raw", "one championship"]
    if re.search(r'\b(?:' + '|'.join(haram_kata) + r')\b', t): return False
    return True

def is_valid_time(start_dt, title):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = title.lower()
    if 5.5 <= w <= 17.5:
        whitelist = ['badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'motogp', 'moto2', 'moto3', 'f1', 'formula', 'wsbk', 'j-league', 'k-league', 'liga 1', 'bri liga', 'afc', 'asian', 'mls', 'nba', 'nfl', 'tennis', 'golf', 'proliga', 'vnl', 'kovo', 'libertadores', 'sudamericana', 'copa', 'brasil', 'argentina', 'concacaf', 'mexico', 'liga mx', 'caf', 'afcon']
        if any(k in t for k in whitelist): return True
        else: return False 
    return True

def parse_time(ts):
    if not ts: return None
    try:
        if len(ts) >= 19 and ('+' in ts or '-' in ts):
            dt = datetime.strptime(ts[:20].strip(), "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
    except: return None

# ========================================================
# 4. EKSEKUSI GABUNGAN
# ========================================================
now_wib = datetime.utcnow() + timedelta(hours=7)
limit_date = now_wib.replace(hour=3, minute=0, second=0, microsecond=0) if now_wib.hour < 3 else (now_wib + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)

epg_dict = {} 
kamus_rumus_epg = {}
jadwal_dict = {} # Menyimpan event/jadwal yang sudah difilter

scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})

print("1. Mengunduh dan memproses EPG (Bypass Anti-Bot)...")
for url in EPG_URLS:
    try:
        resp = scraper.get(url, timeout=60) if "epgshare" in url else requests.get(url, timeout=60)
        if b'<html' in resp.content[:20].lower(): continue
        content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read() if url.endswith('.gz') else resp.content
        
        root = ET.fromstring(content)
        
        # Mapping Channel ID
        for ch in root.findall('channel'):
            id_asli = ch.get('id')
            nama_epg = ch.findtext('display-name') or id_asli
            if id_asli:
                epg_dict[id_asli] = nama_epg
                kamus_rumus_epg[rumus_samakan_teks(id_asli)] = id_asli
                kamus_rumus_epg[rumus_samakan_teks(nama_epg)] = id_asli
        
        # Mapping Jadwal dengan Filter Ketat
        for pg in root.findall('programme'):
            cid = pg.get('channel')
            if cid not in epg_dict: continue
            st, sp = parse_time(pg.get("start")), parse_time(pg.get("stop"))
            title = pg.findtext("title") or ""
            
            if not st or not sp or sp <= now_wib or st >= limit_date: continue 
            durasi = (sp - st).total_seconds() / 60
            
            if is_allowed_sport(title, durasi) and is_valid_time(st, title):
                if cid not in jadwal_dict: jadwal_dict[cid] = []
                logo = pg.find("icon").get("src") if pg.find("icon") is not None else ""
                jadwal_dict[cid].append({
                    "title": bersihkan_judul_event(title),
                    "start": st, "stop": sp, "live": (st - timedelta(minutes=5)) <= now_wib < sp,
                    "logo": logo
                })
    except Exception as e:
        print(f"❌ Gagal EPG {url}: {e}")

daftar_teks_epg_dirumus = list(kamus_rumus_epg.keys())
keranjang_match = {}

print("2. Mencocokkan M3U dengan Jadwal Sultan...")
for url in M3U_URLS:
    try:
        m3u_lines = requests.get(url, timeout=30).text.splitlines()
        block = []
        for ln in m3u_lines:
            ln = ln.strip()
            if not ln or "EXTM3U" in ln.upper(): continue
            if ln.startswith("#"): block.append(ln)
            else:
                if not block: continue
                raw_extinf = next((b for b in block if b.upper().startswith("#EXTINF")), "")
                extra_tags = [b for b in block if not b.upper().startswith("#EXTINF") and not b.upper().startswith("#EXTGRP")]
                block = []
                
                if not raw_extinf or "," not in raw_extinf: continue
                stream_url = ln
                if stream_url in GLOBAL_SEEN_STREAM_URLS: continue
                GLOBAL_SEEN_STREAM_URLS.add(stream_url)
                
                raw_attrs, m3u_name = raw_extinf.split(",", 1)
                m3u_name = m3u_name.strip()
                logo_match = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_attrs)
                orig_logo = logo_match.group(1) if logo_match else ""
                skor_vip = get_vip_score(m3u_name)
                
                clean_attrs = re.sub(r'(?i)\s*(group-title|tvg-group|tvg-id|tvg-logo|tvg-name)=("[^"]*"|\'[^\']*\'|[^\s,]+)', '', raw_attrs).strip()
                if not clean_attrs.upper().startswith("#EXTINF"):
                    clean_attrs = "#EXTINF:-1 " + clean_attrs.replace('#EXTINF:-1', '').replace('#EXTINF:0', '').strip()

                # --- 1. BYPASS JIKA INI EVENT DADAKAN ---
                ev_m = REGEX_EVENT.search(m3u_name)
                if ev_m:
                    hh, mm = int(ev_m.group(1)), int(ev_m.group(2))
                    ev_title = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', ev_m.group(3)).strip()
                    ev_start = now_wib.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if ev_start < now_wib - timedelta(hours=4): ev_start += timedelta(days=1)
                    ev_stop = ev_start + timedelta(hours=2) 
                    
                    if ev_stop > now_wib and ev_start < limit_date:
                        is_live = (ev_start - timedelta(minutes=5)) <= now_wib < ev_stop
                        key = generate_event_key(ev_title, ev_start.timestamp())
                        if key not in keranjang_match: 
                            keranjang_match[key] = {"is_live": is_live, "sort": ev_start.timestamp(), "vip": skor_vip, "links": []}
                        
                        jam_tayang = f"{ev_start.strftime('%H:%M')}-{ev_stop.strftime('%H:%M')}"
                        if is_live:
                            judul = f"{get_flag(ev_title)} 🔴 {jam_tayang} WIB - {ev_title}"
                            inf = f'{clean_attrs} group-title="🔴 SEDANG TAYANG" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                            keranjang_match[key]["links"].append({"prio": 0, "data": [inf] + extra_tags + [stream_url]})
                        else:
                            judul = f"{get_flag(ev_title)} ⏳ {jam_tayang} WIB - {ev_title}"
                            inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{orig_logo}", {judul}'
                            keranjang_match[key]["links"].append({"prio": 0, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                    continue

                # --- 2. JIKA CHANNEL, COCOKKAN PAKAI MAPPING KITA ---
                tvg_id_match = re.search(r'tvg-id="([^"]*)"', raw_attrs)
                id_m3u = tvg_id_match.group(1).strip() if tvg_id_match else ""
                
                kunci_manual = id_m3u.lower() if id_m3u.lower() in kamus_manual else m3u_name.lower()
                id_epg_terpilih = ""
                
                if kunci_manual in kamus_manual:
                    id_epg_terpilih = kamus_manual[kunci_manual]["epg"]
                else:
                    teks_m3u_dirumus = rumus_samakan_teks(id_m3u) or rumus_samakan_teks(m3u_name)
                    if teks_m3u_dirumus in kamus_rumus_epg:
                        id_epg_terpilih = kamus_rumus_epg[teks_m3u_dirumus]
                    else:
                        mirip = difflib.get_close_matches(teks_m3u_dirumus, daftar_teks_epg_dirumus, n=1, cutoff=0.8)
                        if mirip: id_epg_terpilih = kamus_rumus_epg[mirip[0]]

                # --- 3. EKSEKUSI JADWAL (Ubah Nama Jadi Live/Upcoming) ---
                if id_epg_terpilih and id_epg_terpilih in jadwal_dict:
                    for ev in jadwal_dict[id_epg_terpilih]:
                        key = generate_event_key(ev['title'], ev['start'].timestamp())
                        if key not in keranjang_match: 
                            keranjang_match[key] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "vip": skor_vip, "links": []}
                        
                        final_logo = ev["logo"] or orig_logo
                        jam_tayang = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                        
                        if ev["live"]:
                            m_disp = re.sub(r'[\[\]\(\)]', '', m3u_name).strip()
                            judul = f"{get_flag(m3u_name)} 🔴 {jam_tayang} WIB - {ev['title']} [{m_disp}]"
                            inf = f'{clean_attrs} group-title="🔴 SEDANG TAYANG" tvg-id="{id_epg_terpilih}" tvg-logo="{final_logo}", {judul}'
                            keranjang_match[key]["links"].append({"prio": 1, "data": [inf] + extra_tags + [stream_url]})
                        else:
                            judul_pendek = f"{get_flag(m3u_name)} ⏳ {jam_tayang} WIB - {ev['title']}"
                            inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{final_logo}", {judul_pendek}'
                            keranjang_match[key]["links"].append({"prio": 1, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
    except Exception as e:
        print(f"Error memproses M3U {url}: {e}")

print("3. Merender M3U Final (Anti-Lag)...")
hasil_render = []
for key, match in keranjang_match.items():
    links = match["links"]
    unique_links = { l["data"][-1]: l for l in links }.values() 
    sorted_links = sorted(unique_links, key=lambda x: x["prio"])
    
    max_take = 2 if match["is_live"] else 1
    for l in sorted_links[:max_take]:
        hasil_render.append({
            "order": 0 if match["is_live"] else 1,
            "sort": match["sort"],
            "vip": match["vip"],
            "data": l["data"]
        })

hasil_render.sort(key=lambda x: (x["order"], float(x["sort"]), x["vip"]))

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(f'#EXTM3U name="🔴 BAKUL WIFI SPORTS"\n')
    if not hasil_render: 
        f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA PERTANDINGAN\n{LINK_STANDBY}\n')
    else:
        for it in hasil_render: 
            f.write("\n".join(it["data"]) + "\n")
        
print(f"SELESAI! File {OUTPUT_FILE} berhasil dibuat dengan mesin mapping kita & filter sultan Anda!")
