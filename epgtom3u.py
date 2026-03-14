import requests, re, gzip, io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. KONFIGURASI SUMBER (M3U & EPG)
# ==========================================
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/refs/heads/main/astro.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz"
]

MASTER_SOURCES = [
    "https://raw.githubusercontent.com/mimipipi22/lalajo/refs/heads/main/playlist25", # (1)
    "https://semar25.short.gy", "https://deccotech.online/tv/tvstream.html",          # (2,3)
    "https://bit.ly/KPL203", "https://freeiptv2026.tsender57.workers.dev",           # (4,5)
    "https://liveevent.iptvbonekoe.workers.dev", "http://sauridigital.my.id/kerbaunakal/2026TVGNS.html", # (6,7)
    "https://bit.ly/TVKITKAT", "https://spoo.me/tvplurl04", "https://aspaltvpasti.top/xxx/merah.php"    # (8,9,10)
]

OUTPUT_FILE, L_STANDBY, L_UPCOMING = "live_matches_only.m3u", "https://bwifi.my.id/live.mp4", "https://bwifi.my.id/5menit.mp4"
M3U_HEADER = '#EXTM3U url-tvg="https://www.open-epg.com/generate/bXxbrwUThe.xml" name="🔴 BAKUL WIFI TV PREMIUM"'

# ==========================================
# 2. MESIN SENSOR (HUKUM BENUA & DURASI)
# ==========================================
def normalisasi(n):
    n = n.lower().strip()
    n = re.sub(r'\b(?:champions?\s*tv|ctv)\s*(\d+)\b', r'champions tv \1', n)
    return re.sub(r'\bsports?\s+stars?\b', 'sportstars', re.sub(r'\bspo\s+tv\b', 'spotv', n))

def get_flag(n):
    mapping = {'sg':"🇸🇬",'my':"🇲🇾",'th':"🇹🇭",'au':"🇦🇺",'en':"🇬🇧",'ar':"🇸🇦",'id':"🇮🇩"}
    return next((v for k,v in mapping.items() if k in n.lower()), "📺")

def is_allowed(t, c):
    t, c = t.lower(), c.lower()
    # Filter Saluran Non-Sport Global
    ch_haram = ['mekkah','quran','religi','news','berita','cgtn','arirang','cctv','tvri','cnn','ria','oasis','awani','prima','citra']
    if any(x in c for x in ch_haram): return False
    # Filter Kata Haram (Anti-Replay / HL)
    haram = ["delay","replay","re-run","siaran ulang","tunda","cuplikan","sorotan","best of","planet","pre-match","build-up","preview","classic","rewind","(d)","(r)","(c)","highlights","hl "]
    if any(x in t for x in haram): return False
    # Izin Halal
    halal = ["live","langsung","liga","premier","champions","ucl","fa cup","serie a","la liga","bundesliga","timnas","badminton","bwf","voli","motogp","f1","nba","qualifying","practice"," fp1"," fp2"," q1","sesi"]
    return any(x in t for x in halal) or " vs " in t or " v " in t

def is_valid_kickoff(st, sp, t):
    w, durasi, t = st.hour + (st.minute/60.0), (sp-st).total_seconds()/60, t.lower()
    
    # VIP BALAPAN & BADMINTON (Lolos 24 Jam)
    if any(k in t for k in ['badminton','bwf','motogp','f1','qualifying','practice','nba']): return True

    # HUKUM DURASI BOLA (Wajib > 85 Menit)
    is_ball = any(x in t for x in ['liga','premier','champions','serie','bundesliga','vs',' v '])
    if is_ball and (durasi < 85 or durasi > 185): return False

    # HUKUM BENUA (KALIBRASI FINAL)
    rules = [
        (['premier','champions league','serie a','la liga','bundesliga','ucl','uefa','fa cup'], w >= 18.0 or w <= 4.0), # EROPA
        (['mls','major league','concacaf','libertadores','sudamericana','liga mx','brasileiro'], 2.0 <= w <= 11.5),      # AMERIKA
        (['j-league','k-league','afc','asian','aff','liga 1','bri liga','timnas'], 11.5 <= w <= 22.5),              # ASIA/INDO
        (['saudi','roshn','caf ','africa','afcon'], w >= 20.0 or w <= 6.5),                                         # AFRIKA/ARAB (Hingga 06:30 Pagi)
        (['a-league','nrl','afl'], 7.5 <= w <= 17.5)                                                                # AUSTRALIA
    ]
    for keys, cond in rules:
        if any(k in t for k in keys): return cond
    
    # Fallback VS (Penyelamat jika liganya tidak tertulis di EPG)
    return not (4.5 < w < 11.0 and " vs " not in t)

# ==========================================
# 3. PROSES DATA (MAIN EXECUTION)
# ==========================================
def main():
    now = datetime.utcnow() + timedelta(hours=7)
    epg_chans, epg_logos, match_data = {}, {}, {}
    limit = (now + timedelta(days=2 if now.hour < 5 else 3)).replace(hour=5, minute=0)
    ses = requests.Session()
    ses.headers.update({'User-Agent': 'Mozilla/5.0'})

    print("Step 1: Sedot EPG...")
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
                cid, title = pg.get("channel"), pg.findtext("title") or ""
                if cid not in epg_chans or not is_allowed(title, epg_chans[cid]): continue
                st = datetime.strptime(pg.get("start")[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
                sp = datetime.strptime(pg.get("stop")[:14], "%Y%m%d%H%M%S") + timedelta(hours=7)
                if st >= limit or sp <= now or not is_valid_kickoff(st, sp, title): continue
                if cid not in match_data: match_data[cid] = []
                match_data[cid].append({"t": re.sub(r'(?i)(\(l\)|\[l\]|live|langsung)', '', title).strip(), "st": st, "sp": sp, "live": (st-timedelta(minutes=10)) <= now < sp, "logo": (pg.find("icon").get("src") if pg.find("icon") is not None else "")})
        except: continue

    print("Step 2: Sedot M3U & Audit...")
    res, live_track, up_track = [], set(), set()
    for idx, url in enumerate(MASTER_SOURCES, 1):
        try:
            lines = ses.get(url, timeout=30).text.splitlines()
            block = []
            for ln in lines:
                if not ln.strip() or "EXTM3U" in ln: continue
                if ln.startswith("#"): block.append(ln)
                else:
                    ext = next((t for t in block if "EXTINF" in t), None)
                    if ext and "," in ext:
                        mname = ext.split(",")[-1].strip()
                        for cid, ename in epg_chans.items():
                            en, mn = normalisasi(ename), normalisasi(mname)
                            if en in mn or mn in en:
                                if cid in match_data:
                                    for ev in match_data[cid]:
                                        jam = f"{ev['st'].strftime('%H:%M')}-{ev['sp'].strftime('%H:%M')} WIB"
                                        logo = ev["logo"] or epg_logos.get(cid) or ""
                                        flag = get_flag(mname)
                                        if ev["live"]:
                                            if f"{cid}_{ev['st'].timestamp()}_{ln}" in live_track: continue
                                            live_track.add(f"{cid}_{ev['st'].timestamp()}_{ln}")
                                            res.append({"o":0, "t":ev["st"].timestamp(), "s":ev['t'], "b":[f'#EXTINF:-1 group-title="🔴 ACARA SEDANG TAYANG" tvg-id="{cid}" tvg-logo="{logo}", {flag} 🔴 {jam} - {ev["t"]} [{mname}] ({idx})', ln]})
                                        else:
                                            k_up = f"{ev['st'].strftime('%Y%m%d%H%M')}_{re.sub(r'[^a-z0-9]','',ev['t'].lower())}"
                                            if k_up in up_track: continue
                                            up_track.add(k_up)
                                            lbl = "Besok " if ev['st'].date() == (now.date()+timedelta(days=1)) else "Lusa " if ev['st'].date() == (now.date()+timedelta(days=2)) else ""
                                            res.append({"o":1, "t":ev["st"].timestamp(), "s":ev['t'], "b":[f'#EXTINF:-1 group-title="📅 ACARA AKAN DATANG" tvg-id="{cid}" tvg-logo="{logo}", {flag} ⏳ {lbl}{jam} - {ev["t"]} ({idx})', L_UPCOMING]})
                    block = []
        except: continue

    print("Step 3: Simpan Hasil Final...")
    res.sort(key=lambda x: (x["o"], x["t"], x["s"]))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(M3U_HEADER + '\n')
        if not res: f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA JADWAL\n{L_STANDBY}\n')
        for item in res: f.write("\n".join(item["b"]) + "\n")

if __name__ == "__main__": main()
