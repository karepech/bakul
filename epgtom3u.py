import requests, re, gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import concurrent.futures
from functools import lru_cache

# ==========================================
# I. KONFIGURASI EMAS (ULTRA-LIGHT STB)
# ==========================================
MAP_URL = "https://raw.githubusercontent.com/karepech/bakul/refs/heads/main/map.txt"

EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",                   
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"                   
]

M3U_URLS = [

    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/event_combined.m3u",
    "https://raw.githubusercontent.com/karepech/Karepetv/refs/heads/main/sports_combined.m3u"
]

OUTPUT_FILE = "live_matches_only.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

GLOBAL_SEEN_STREAM_URLS = set()
MAPPING_DICT = {}
COMPILED_MAPPING = []

# ==========================================
# II. SISTEM MAPPING KAMUS PINTAR (TURBO)
# ==========================================
def load_mapping():
    global MAPPING_DICT, COMPILED_MAPPING
    try:
        r = requests.get(MAP_URL, timeout=30).text
        for line in r.splitlines():
            line = line.split('#')[0].strip() 
            if not line or line.startswith('['): continue
            if '=' in line:
                official, aliases = line.split('=', 1)
                official = official.strip().lower()
                for alias in aliases.split(','):
                    alias = alias.strip().lower()
                    if alias: MAPPING_DICT[alias] = official
        
        MAPPING_DICT = dict(sorted(MAPPING_DICT.items(), key=lambda x: len(x[0]), reverse=True))
        for alias, official in MAPPING_DICT.items():
            COMPILED_MAPPING.append((re.compile(r'\b' + re.escape(alias) + r'\b'), official))
        print(f"Berhasil mengkompilasi {len(MAPPING_DICT)} istilah dari map.txt!")
    except Exception as e:
        print(f"Gagal memuat map.txt: {e}")

@lru_cache(maxsize=None)
def terjemahkan_nama(teks):
    if not teks: return ""
    n = teks.lower().strip()
    for pattern, official in COMPILED_MAPPING:
        n = pattern.sub(official, n)
    return n

# ==========================================
# III. OPTIMASI FUNGSI & FILTERING
# ==========================================
REGEX_CYRILLIC_CJK = re.compile(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]')
REGEX_KUALITAS = re.compile(r'\b(hd|fhd|uhd|4k|8k|tv|hevc|raw|plus|max|sd|hq|sport|sports|ch|channel|network|premium|now)\b')
REGEX_NUMBERS = re.compile(r'\d+')
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

@lru_cache(maxsize=10000)
def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    return re.sub(r'^[\-\:\,\|]\s*', '', re.sub(r'\s+', ' ', bersih)).strip()

@lru_cache(maxsize=10000)
def generate_event_key(title, timestamp):
    tc = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', title)
    tc = re.sub(r'\d+\]?$', '', tc.strip())
    return f"{REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', tc.lower()))}_{timestamp}"

@lru_cache(maxsize=5000)
def get_vip_score(ch_name):
    n = ch_name.lower()
    if any(k in n for k in ['bein', 'spotv', 'sportstars', 'soccer channel', 'champions tv', 'rcti sports', 'inews sports', 'mnc sports']): return 0
    return 1

@lru_cache(maxsize=5000)
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
    if 'bein' in n and not any(x in n for x in [' us', ' usa', ' sg', ' my', ' uk', ' th', ' hk', ' au', ' ae', ' za', ' ph']): return "🇮🇩"
    return "📺" 

def get_region_ktp(name, epg_id=""):
    n = (name + " " + epg_id).lower()
    for reg, kws in [("US",['.us',' us','usa','america']), ("AU",['.au',' au','aus','optus']), ("UK",['.uk',' uk','eng','english','sky']), ("ARAB",['.ae',' ar','arab','mena','ssc']), ("MY",['.my',' my','malaysia']), ("TH",['.th',' th','thai','true']), ("SG",['.sg',' sg','singapore','hub']), ("ZA",['.za',' za','supersport']), ("HK",['.hk',' hk','hong']), ("PH",['.ph',' ph','phil']), ("ID",['.id',' id','indo','indonesia'])]:
        if any(x in n for x in kws): return reg
    return "UNKNOWN"

@lru_cache(maxsize=10000)
def is_sports_channel(name):
    n = terjemahkan_nama(name)
    if 'astro' in n: return False
    lokal = ['rcti', 'sctv', 'antv', 'indosiar', 'tvri', 'mnc', 'trans', 'global', 'inews']
    if any(x in n for x in lokal) and 'soccer channel' not in n: return 'sport' in n
    sports_kws = ['bein', 'spotv', 'sport', 'soccer', 'champions', 'espn', 'golf', 'tennis', 'motor', 'mola', 'vidio', 'cbs', 'sky', 'tnt', 'optus', 'hub', 'true premier', 'true sport', 'supersport', 'dazn', 'setanta', 'eleven', 'now sports', 'fox', 'tsn', 'ssc', 'alkass', 'abu dhabi', 'dubai']
    return any(x in n for x in sports_kws)

def is_allowed_sport(title, ch_name, durasi_menit):
    if not title: return False
    t = terjemahkan_nama(title)
    
    if REGEX_CYRILLIC_CJK.search(t) or durasi_menit <= 30: return False
    
    haram_simbol = ["(d)", "[d]", "(r)", "[r]", "(c)", "[c]", "hls", "hl ", "h/l", "rev ", "rep ", "del "]
    if any(s in t for s in haram_simbol): return False
    
    haram_kata = ["replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary", "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", "sepak mula", "dokumenter", "obrolan", "bincang", "berita", "news", "apa kabar", "religi", "quran", "mekkah", "masterchef", "cgtn", "arirang", "cnn", "lfctv", "mutv", "chelsea tv", "re-live", "relive", "history", "retro", "memories", "greatest", "wwe", "ufc", "mma", "boxing", "fight", "smackdown", "raw", "one championship"]
    if re.search(r'\b(?:' + '|'.join(haram_kata) + r')\b', t): return False
    return True

def is_valid_time(start_dt, title):
    w = start_dt.hour + (start_dt.minute / 60.0)
    t = terjemahkan_nama(title)
    
    if 5.5 <= w <= 17.5:
        whitelist = [
            'badminton', 'bwf', 'thomas', 'uber', 'sudirman',
            'motogp', 'moto2', 'moto3', 'f1', 'formula', 'wsbk',
            'j-league', 'k-league', 'liga 1', 'bri liga', 'afc', 'asian',
            'mls', 'nba', 'nfl', 'tennis', 'golf', 'proliga', 'vnl', 'kovo',
            'libertadores', 'sudamericana', 'copa', 'brasil', 'argentina', 'concacaf',
            'mexico', 'liga mx', 'caf', 'afcon'
        ]
        if any(k in t for k in whitelist): return True
        else: return False 
    return True

@lru_cache(maxsize=10000)
def is_match_akurat_v3(epg_name, epg_id, m3u_name):
    e = terjemahkan_nama(epg_name)
    m = terjemahkan_nama(m3u_name)
    
    for b in ['bein', 'spotv', 'champions tv', 'sportstars', 'soccer channel', 'true premier', 'dazn', 'setanta', 'supersport']:
        if (b in e) != (b in m): return False
        
    if ('xtra' in e or 'extra' in e) != ('xtra' in m or 'extra' in m): return False
    if ('connect' in e) != ('connect' in m): return False
        
    e_c = re.sub(r'(liga 1|laliga 1|formula 1|f 1|f1|liga 2)', '', e).strip()
    m_c = re.sub(r'(liga 1|laliga 1|formula 1|f 1|f1|liga 2)', '', m).strip()
    
    if re.search(r'\b(spotv|bein)\b', e_c) and not REGEX_NUMBERS.search(e_c) and not re.search(r'(xtra|extra|connect)', e_c): e_c += ' 1'
    if re.search(r'\b(spotv|bein)\b', m_c) and not REGEX_NUMBERS.search(m_c) and not re.search(r'(xtra|extra|connect)', m_c): m_c += ' 1'
    
    e_k = REGEX_KUALITAS.sub('', e_c).strip()
    m_k = REGEX_KUALITAS.sub('', m_c).strip()
    e_num = REGEX_NUMBERS.findall(e_k)
    m_num = REGEX_NUMBERS.findall(m_k)
    en = e_num[0] if e_num else '0'
    mn = m_num[0] if m_num else '0'
    
    if not any(k in e_k for k in ['badminton']) and en != mn: return False
    
    ktp_e = get_region_ktp(epg_name, epg_id)
    ktp_m = get_region_ktp(m3u_name)
    if 'bein' in e or 'spotv' in e:
        if (ktp_e if ktp_e != "UNKNOWN" else "ID") != (ktp_m if ktp_m != "UNKNOWN" else "ID"): return False
    elif ktp_e != "UNKNOWN" and ktp_m != "UNKNOWN" and ktp_e != ktp_m: return False
    
    if e_k in m_k or m_k in e_k: return True
    e_words = set(re.findall(r'[a-z0-9]+', e_k))
    m_words = set(re.findall(r'[a-z0-9]+', m_k))
    if e_words and m_words and (e_words.issubset(m_words) or m_words.issubset(e_words)): return True
    return False

def parse_time(ts):
    if not ts: return None
    try:
        if len(ts) >= 19 and ('+' in ts or '-' in ts):
            dt = datetime.strptime(ts[:20].strip(), "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
    except Exception: return None

def fetch_url_content(url, is_epg=False):
    try:
        ses = requests.Session()
        ses.headers.update({'User-Agent': 'Mozilla/5.0'})
        r = ses.get(url, timeout=60).content
        if is_epg:
            return url, (gzip.decompress(r) if r[:2] == b'\x1f\x8b' else r), True
        return url, r.decode('utf-8', errors='ignore'), False
    except Exception as e:
        print(f"Gagal mengunduh {url}: {e}")
        return url, None, is_epg

# ==========================================
# VI. PROSES EKSEKUSI UTAMA
# ==========================================
def main():
    now_wib = datetime.utcnow() + timedelta(hours=7)
    match_data, epg_chans, epg_logos = {}, {}, {}
    
    if now_wib.hour < 3:
        limit_date = now_wib.replace(hour=3, minute=0, second=0, microsecond=0)
    else:
        limit_date = (now_wib + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)

    load_mapping()
    
    print(f"Menyapu jadwal hingga {limit_date.strftime('%d-%m-%Y %H:%M WIB')}...")
    epg_contents, m3u_contents = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_url_content, u, True) for u in EPG_URLS]
        futures += [executor.submit(fetch_url_content, u, False) for u in M3U_URLS]
        for f in concurrent.futures.as_completed(futures):
            url, content, is_epg = f.result()
            if content:
                if is_epg: epg_contents[url] = content
                else: m3u_contents[url] = content

    for content in epg_contents.values():
        try:
            root = ET.fromstring(content)
            for ch in root.findall("channel"):
                cid, cn = ch.get("id"), ch.findtext("display-name")
                if cid and cn and is_sports_channel(cn): 
                    epg_chans[cid] = cn.strip()
                    icon = ch.find("icon")
                    if icon is not None: epg_logos[cid] = icon.get("src")
            for pg in root.findall("programme"):
                cid = pg.get("channel")
                if cid not in epg_chans: continue 
                st, sp = parse_time(pg.get("start")), parse_time(pg.get("stop"))
                
                if not st or not sp or sp <= now_wib or st >= limit_date: continue 
                
                durasi = (sp - st).total_seconds() / 60
                title = pg.findtext("title") or ""
                if is_allowed_sport(title, epg_chans[cid], durasi) and is_valid_time(st, title):
                    if cid not in match_data: match_data[cid] = []
                    match_data[cid].append({"title": bersihkan_judul_event(title), "start": st, "stop": sp, "live": (st - timedelta(minutes=5)) <= now_wib < sp, "logo": pg.find("icon").get("src") if pg.find("icon") is not None else ""})
        except: continue

    keranjang_match = {} 
    
    for url, content in m3u_contents.items():
        lines = content.splitlines()
        block = []
        for ln in lines:
            ln = ln.strip()
            if not ln or "EXTM3U" in ln.upper(): continue
            if ln.startswith("#"):
                if ln.upper().startswith("#EXTINF"): block = [ln]
                else: block.append(ln)
            else:
                if not block: continue
                raw_extinf = block[0]
                stream_url = ln 
                
                # Tag Ekstra (seperti #EXTVLCOPT) diamankan
                extra_tags = [t for t in block[1:] if not t.upper().startswith("#EXTGRP")]
                
                if "KPL203" in url and not re.search(r'(?i)group-title=["\'][^"\']*event', raw_extinf): 
                    block = []
                    continue
                
                if "," in raw_extinf:
                    raw_attrs, m3u_name = raw_extinf.split(",", 1)
                    m3u_name = m3u_name.strip()
                    
                    if stream_url in GLOBAL_SEEN_STREAM_URLS:
                        block = []
                        continue
                    GLOBAL_SEEN_STREAM_URLS.add(stream_url)
                    
                    logo_match = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_attrs)
                    orig_logo = logo_match.group(1) if logo_match else ""
                    skor_vip = get_vip_score(m3u_name)
                    
                    # 💥 FOKUS FULL CODE: Menyaring group, id, logo, dan nama lama dari atribut asli
                    clean_attrs = re.sub(r'(?i)\s*(group-title|tvg-group|tvg-id|tvg-logo|tvg-name)=("[^"]*"|\'[^\']*\'|[^\s,]+)', '', raw_attrs).strip()
                    if not clean_attrs.upper().startswith("#EXTINF"):
                        clean_attrs = "#EXTINF:-1 " + clean_attrs.replace('#EXTINF:-1', '').replace('#EXTINF:0', '').strip()
                    
                    ev_m = REGEX_EVENT.search(m3u_name)
                    # 1. JALUR JAM TAYANG
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
                                # PENERAPAN FULL CODE ASLI PROVIDER DI SINI
                                inf = f'{clean_attrs} group-title="🔴 SEDANG TAYANG" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                                keranjang_match[key]["links"].append({"prio": 0, "data": [inf] + extra_tags + [stream_url]})
                            else:
                                judul = f"{get_flag(ev_title)} ⏳ {jam_tayang} WIB - {ev_title}"
                                inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{orig_logo}", {judul}'
                                keranjang_match[key]["links"].append({"prio": 0, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                                
                    # 2. JALUR EPG
                    elif is_sports_channel(m3u_name):
                        for cid, ename in epg_chans.items():
                            if is_match_akurat_v3(ename, cid, m3u_name) and cid in match_data:
                                for ev in match_data[cid]:
                                    key = generate_event_key(ev['title'], ev['start'].timestamp())
                                    
                                    if key not in keranjang_match: 
                                        keranjang_match[key] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "vip": skor_vip, "links": []}
                                    
                                    final_logo = ev["logo"] or epg_logos.get(cid) or orig_logo
                                    jam_tayang = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                                    
                                    if ev["live"]:
                                        m_disp = re.sub(r'[\[\]\(\)]', '', m3u_name).strip()
                                        judul = f"{get_flag(m3u_name)} 🔴 {jam_tayang} WIB - {ev['title']} [{m_disp}]"
                                        # PENERAPAN FULL CODE ASLI PROVIDER DI SINI JUGA
                                        inf = f'{clean_attrs} group-title="🔴 SEDANG TAYANG" tvg-id="{cid}" tvg-logo="{final_logo}", {judul}'
                                        keranjang_match[key]["links"].append({"prio": 1, "data": [inf] + extra_tags + [stream_url]})
                                    else:
                                        judul_pendek = f"{get_flag(m3u_name)} ⏳ {jam_tayang} WIB - {ev['title']}"
                                        inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{final_logo}", {judul_pendek}'
                                        keranjang_match[key]["links"].append({"prio": 1, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                block = []

    print("Step 4: Rendering M3U Anti-Lag...")
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
            
    print(f"SELESAI! Jadwal Live sekarang FULL CODE Murni tanpa kepotong!")

if __name__ == "__main__": main()
