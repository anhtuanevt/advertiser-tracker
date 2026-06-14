#!/usr/bin/env python3
"""
QC Tracker — Update Script
==========================
Workflow:
  1. Paste raw data (TSV) vào raw_data.txt
  2. Chạy: python3 update.py
  3. File index.html tự sinh → deploy lên Vercel/netlify/bất cứ đâu

Tự động:
  - Normalize URL (bỏ UTM, www, tracking params)
  - So sánh với snapshot trước → highlight MỚI / ĐỔI / XÓA
  - Tạo link Facebook Ad Library cho từng nhà QC
  - Ghi timestamp cập nhật
"""

import csv
import json
import os
import re
from datetime import datetime
from urllib.parse import quote, urlparse

# ==================== CONFIG ====================
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RAW_FILE    = os.path.join(BASE_DIR, "raw_data.txt")
SNAPSHOT_DIR= os.path.join(BASE_DIR, "snapshots")
OUTPUT_HTML = os.path.join(BASE_DIR, "index.html")
# Also copy to vercel-app/public for deploy
DEPLOY_HTML = os.path.join(BASE_DIR, "vercel-app", "public", "index.html")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# ==================== HELPERS ====================

def normalize_url(raw):
    if not raw or not raw.strip():
        return "", ""
    url = raw.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        clean = f"https://{domain}"
    except:
        domain = url
        clean = url
    return domain, clean

def make_ad_url(partner):
    return f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL&q={quote(partner)}&search_type=keyword_unordered"

def parse_raw_data(filepath):
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()
    
    data_lines = lines[1:]
    records = []
    partner_stats = {}
    partner_ads_link = {}
    
    for line in data_lines:
        cols = [c.strip() for c in line.split("\t")]
        while cols and cols[-1] == "":
            cols.pop()
        if len(cols) < 2:
            continue
        partner = cols[0].strip()
        if not partner:
            continue
        
        # Extract Ads Transparency link from last column if present
        ads_link = ""
        if cols and ("adstransparency" in cols[-1].lower() or (cols[-1].startswith("http") and "ads" in cols[-1].lower())):
            ads_link = cols[-1].strip()
            cols = cols[:-1]
            while cols and cols[-1] == "":
                cols.pop()
        if ads_link:
            partner_ads_link[partner] = ads_link
        
        if len(cols) < 2:
            if partner not in partner_stats:
                partner_stats[partner] = {"total": 0, "running": 0}
            continue
        
        remaining = cols[1:]
        i = 0
        while i < len(remaining):
            url_raw = remaining[i].strip() if i < len(remaining) else ""
            status_raw = remaining[i+1].strip() if i+1 < len(remaining) else ""
            if not url_raw:
                i += 2
                continue
            status = "Đang chạy"
            if status_raw:
                s = status_raw.lower()
                if "ngưng" in s or "stop" in s or "paused" in s:
                    status = "Ngưng chạy"
            domain, clean = normalize_url(url_raw)
            ad_url = partner_ads_link.get(partner, "") or make_ad_url(partner)
            records.append({
                "partner": partner,
                "url_original": url_raw,
                "domain": domain,
                "url_normalized": clean,
                "status": status,
                "ad_library_url": ad_url,
            })
            i += 2
        
        if partner not in partner_stats:
            partner_stats[partner] = {"total": 0, "running": 0}
    
    for r in records:
        ps = partner_stats.setdefault(r["partner"], {"total": 0, "running": 0})
        ps["total"] += 1
        if r["status"] == "Đang chạy":
            ps["running"] += 1
    
    summary = [{"partner": p, "total": s["total"], "running": s["running"]} for p, s in partner_stats.items()]
    return records, summary

def build_snapshot(records):
    snap = {}
    for r in records:
        snap[f"{r['partner']}|{r['domain']}"] = r["status"]
    return snap

def detect_changes(records, prev_snap):
    if not prev_snap:
        for r in records:
            r["change"] = "same"
        return False, []
    
    current_keys = set()
    for r in records:
        key = f"{r['partner']}|{r['domain']}"
        current_keys.add(key)
        if key not in prev_snap:
            r["change"] = "new"
        elif prev_snap[key] != r["status"]:
            r["change"] = "changed"
            r["old_status"] = prev_snap[key]
        else:
            r["change"] = "same"
    
    removed = []
    for key, status in prev_snap.items():
        if key not in current_keys:
            idx = key.find("|")
            if idx > 0:
                removed.append({
                    "partner": key[:idx],
                    "domain": key[idx+1:],
                    "url_normalized": f"https://{key[idx+1:]}",
                    "status": status,
                })
    return True, removed

def build_partner_history(snapshot_dir, current_records, current_timestamp):
    """Read all snapshots chronologically + current data → per-partner history events."""
    snapshots = sorted([f for f in os.listdir(snapshot_dir) if f.endswith(".json")])
    
    timeline = []  # [{timestamp, data: {partner|domain: status}}]
    for snap_file in snapshots:
        with open(os.path.join(snapshot_dir, snap_file), encoding="utf-8") as f:
            snap = json.load(f)
        timeline.append({"timestamp": snap.get("timestamp",""), "data": snap.get("data",{})})
    
    # Add current as last entry
    current_map = {}
    for r in current_records:
        current_map[f"{r['partner']}|{r['domain']}"] = r["status"]
    timeline.append({"timestamp": current_timestamp, "data": current_map})
    
    # Build per-partner history
    partner_history = {}  # {partner: [{date, domain, action, status, old_status}]}
    
    prev = {}
    for snap in timeline:
        curr = snap["data"]
        ts = snap["timestamp"]
        
        for key, status in curr.items():
            idx = key.find("|")
            if idx <= 0: continue
            partner = key[:idx]
            domain = key[idx+1:]
            
            entry = partner_history.setdefault(partner, [])
            
            if key not in prev:
                entry.append({"date": ts, "domain": domain, "action": "added", "status": status})
            elif prev[key] != status:
                entry.append({"date": ts, "domain": domain, "action": "status_change", "status": status, "old_status": prev[key]})
        
        for key, status in prev.items():
            if key not in curr:
                idx = key.find("|")
                if idx <= 0: continue
                partner = key[:idx]
                domain = key[idx+1:]
                entry = partner_history.setdefault(partner, [])
                entry.append({"date": ts, "domain": domain, "action": "removed", "status": status})
        
        prev = curr
    
    # Build last-update map: {partner|domain: last_event_date}
    last_update = {}
    for partner, events in partner_history.items():
        for ev in events:
            if ev["action"] in ("added", "status_change"):
                key = f"{partner}|{ev['domain']}"
                last_update[key] = ev["date"]
    
    return partner_history, last_update

def js_escape(s):
    return str(s).replace("\\","\\\\").replace("'","\\'").replace('"','\\"').replace("\n"," ").replace("\r","")

def build_html(records, summary, removed, has_comparison, timestamp, prev_timestamp, partner_history, ads_links, last_update):
    detail_js = []
    for r in records:
        key = f"{r['partner']}|{r['domain']}"
        r_date = last_update.get(key, timestamp)
        detail_js.append(
            '{partner:"%s",url_original:"%s",domain:"%s",url_normalized:"%s",status:"%s",ad_library_url:"%s",change:"%s",old_status:"%s",last_date:"%s"}'
            % tuple(js_escape(r.get(k,"") if k!="last_date" else r_date) for k in ["partner","url_original","domain","url_normalized","status","ad_library_url","change","old_status","last_date"])
        )
    
    partner_new = {}
    for r in records:
        if r.get("change") == "new":
            partner_new[r["partner"]] = partner_new.get(r["partner"], 0) + 1
    summary_js = []
    for s in summary:
        summary_js.append('{partner:"%s",total:%d,running:%d,new_count:%d}' % (
            js_escape(s["partner"]), s["total"], s["running"], partner_new.get(s["partner"], 0)
        ))
    
    removed_js = []
    for r in removed:
        removed_js.append('{partner:"%s",domain:"%s",url_normalized:"%s",status:"%s"}' % (
            js_escape(r["partner"]), js_escape(r["domain"]), js_escape(r["url_normalized"]), js_escape(r["status"])
        ))
    
    # Build history JS: {partner: [{date, domain, action, status, old_status}]}
    history_js_parts = []
    for partner, events in partner_history.items():
        ev_js = []
        for ev in events:
            ev_js.append('{date:"%s",domain:"%s",action:"%s",status:"%s",old_status:"%s"}' % (
                js_escape(ev["date"]), js_escape(ev["domain"]), js_escape(ev["action"]),
                js_escape(ev.get("status","")), js_escape(ev.get("old_status",""))
            ))
        history_js_parts.append('"%s":[%s]' % (js_escape(partner), ",".join(ev_js)))
    history_js = "{%s}" % ",".join(history_js_parts)
    
    # Build ads links JS
    ads_js_parts = []
    for partner, link in ads_links.items():
        ads_js_parts.append('"%s":"%s"' % (js_escape(partner), js_escape(link)))
    ads_links_js = "{%s}" % ",".join(ads_js_parts)
    
    new_count = sum(1 for r in records if r.get("change") == "new")
    changed_count = sum(1 for r in records if r.get("change") == "changed")
    removed_count = len(removed)
    total_changes = new_count + changed_count + removed_count
    
    compare_info = f'(so với lần trước: <strong>{prev_timestamp}</strong>)' if has_comparison and prev_timestamp else ""
    
    HTML = r'''<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Danh sách nhà QC & Dự án</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;color:#1a1a2e;padding:12px 20px}
h1{text-align:center;margin-bottom:2px;color:#16213e;font-size:22px}
.subtitle{text-align:center;color:#666;margin-bottom:2px;font-size:13px}
.update-time{text-align:center;color:#999;font-size:12px;margin-bottom:10px}
.update-time strong{color:#0f3460}
.stats{display:flex;gap:10px;justify-content:center;margin-bottom:10px;flex-wrap:wrap}
.stat-card{background:#fff;border-radius:10px;padding:8px 18px;box-shadow:0 1px 4px rgba(0,0,0,.06);text-align:center;min-width:100px}
.stat-card .num{font-size:22px;font-weight:700;color:#0f3460}
.stat-card .label{font-size:11px;color:#888;margin-top:2px}
.stat-card.changes .num{color:#e94560}
.controls{display:flex;gap:10px;justify-content:center;margin-bottom:10px;flex-wrap:wrap}
.controls input,.controls select{padding:7px 14px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none;transition:border-color .2s}
.controls input{width:260px}
.controls input:focus,.controls select:focus{border-color:#0f3460}
.tabs{display:flex;gap:0;justify-content:center;margin-bottom:10px}
.tab{padding:7px 22px;cursor:pointer;border:1px solid #ddd;background:#fff;font-size:13px;font-weight:500;color:#666;transition:all .2s}
.tab:first-child{border-radius:8px 0 0 8px}
.tab:not(:first-child){border-left:none}
.tab:last-child{border-radius:0 8px 8px 0}
.tab.active{background:#0f3460;color:#fff;border-color:#0f3460}
.table-wrap{background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;max-height:calc(100vh - 250px);overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
thead{position:sticky;top:0;background:#16213e;color:#fff;z-index:10}
thead th{padding:9px 12px;text-align:left;font-weight:600;white-space:nowrap;cursor:pointer;user-select:none}
thead th:hover{background:#0f3460}
thead th .sort-indicator{opacity:.4;font-size:11px;margin-left:4px}
tbody tr{border-bottom:1px solid #f0f0f0;transition:background .15s}
tbody tr:hover{background:#f7f9fc}
tbody td{padding:7px 12px;vertical-align:middle}
tbody td a{color:#0f3460;text-decoration:none;word-break:break-all}
tbody td a:hover{text-decoration:underline}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.badge.running{background:#d4edda;color:#155724}
.badge.stopped{background:#f8d7da;color:#721c24}
.badge.new{background:#cce5ff;color:#004085}
.badge.removed{background:#f8d7da;color:#721c24}
.badge.changed{background:#fff3cd;color:#856404}
.partner-cell{font-weight:600;color:#16213e}
.domain-cell{color:#888;font-size:12px}
.url-orig-cell{color:#aaa;font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.no-results{text-align:center;padding:40px;color:#999}
.partner-group-row{background:#eef2f7;font-weight:700;color:#0f3460}
.partner-group-row td{padding:8px 14px;font-size:12px}
.partner-group-row .count{float:right;background:#0f3460;color:#fff;padding:2px 10px;border-radius:12px;font-size:11px}
tr.row-new{background:#e7f4ff!important}
tr.row-new:hover{background:#d1ecff!important}
tr.row-changed{background:#fffbea!important}
tr.row-changed:hover{background:#fff3cd!important}
.chip.active{font-weight:600}
.chip-all{border-color:#16213e;color:#16213e}
.chip-all.active{background:#16213e;color:#fff}
.chip-new{border-color:#004085;color:#004085}
.chip-new.active{background:#cce5ff}
.chip-changed{border-color:#856404;color:#856404}
.chip-changed.active{background:#fff3cd}
.chip-same{border-color:#155724;color:#155724}
.chip-same.active{background:#d4edda}
.ad-link{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:600;background:#1a73e8;color:#fff!important;text-decoration:none!important;white-space:nowrap;transition:background .2s}
.ad-link:hover{background:#1557b0}
.ad-link svg{width:14px;height:14px;fill:#fff}
.copy-btn{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border:none;border-radius:4px;background:#e8eaf0;color:#5a6a85;cursor:pointer;transition:all .2s;vertical-align:middle;margin-left:4px}
.copy-btn:hover{background:#0f3460;color:#fff}
.copy-btn svg{width:13px;height:13px;fill:currentColor}
.copy-btn.copied{background:#28a745;color:#fff}
/* Modal */
.modal-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:1000;justify-content:center;align-items:flex-start;padding:40px 20px;overflow-y:auto}
.modal-overlay.active{display:flex}
.modal{background:#fff;border-radius:16px;width:100%;max-width:900px;box-shadow:0 20px 60px rgba(0,0,0,.3);overflow:hidden}
.modal-header{background:#16213e;color:#fff;padding:20px 28px;display:flex;justify-content:space-between;align-items:center}
.modal-header h2{font-size:20px;font-weight:700;margin:0}
.modal-close{background:none;border:none;color:#fff;font-size:28px;cursor:pointer;line-height:1;padding:0;opacity:.8;transition:opacity .2s}
.modal-close:hover{opacity:1}
.modal-body{padding:24px 28px;max-height:70vh;overflow-y:auto}
.modal-section{margin-bottom:24px}
.modal-section h3{font-size:14px;color:#16213e;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #eef2f7}
.modal-table{width:100%;border-collapse:collapse;font-size:13px}
.modal-table th{padding:8px 12px;text-align:left;background:#eef2f7;color:#16213e;font-weight:600;font-size:12px;text-transform:uppercase}
.modal-table td{padding:10px 12px;border-bottom:1px solid #f0f0f0;vertical-align:middle}
.modal-table td a{color:#0f3460;text-decoration:none}
.modal-table td a:hover{text-decoration:underline}
.timeline-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #f5f5f5;align-items:center}
.timeline-date{font-size:12px;color:#888;white-space:nowrap;min-width:130px;font-weight:600}
.timeline-action{font-size:13px}
.timeline-action .badge{margin-right:6px}
.timeline-domain{color:#0f3460;font-weight:500}
.modal-ad-link{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;background:#1a73e8;color:#fff!important;text-decoration:none!important;transition:background .2s}
.modal-ad-link:hover{background:#1557b0}
.modal-ad-link svg{width:16px;height:16px;fill:#fff}
.modal-stats{display:flex;gap:16px;margin-bottom:20px}
.modal-stat{background:#f7f9fc;border-radius:8px;padding:10px 20px;text-align:center}
.modal-stat .num{font-size:22px;font-weight:700;color:#0f3460}
.modal-stat .lbl{font-size:11px;color:#888}
.url-cell-wrap{display:inline-flex;align-items:center;gap:2px}
.top-bar{display:flex;align-items:center;gap:16px;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap}
.top-bar .stats{margin-bottom:0}
.top-bar .controls{margin-bottom:0}
.change-filters{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.chip{padding:5px 12px;border-radius:20px;font-size:12px;cursor:pointer;border:2px solid transparent;background:#fff;transition:all .2s}
.change-filters{display:flex;gap:6px;justify-content:center;margin-bottom:0;flex-wrap:wrap}
</style>
</head>
<body>
<h1>Danh sách nhà QC &amp; Dự án</h1>
<p class="subtitle">Dữ liệu đã chuẩn hóa</p>
<p class="update-time">Cập nhật lúc: <strong id="updateTime">__TIMESTAMP__</strong> <span id="compareInfo" style="margin-left:16px;color:#e94560">__COMPARE_INFO__</span></p>
<div class="top-bar">
<div class="stats">
<div class="stat-card"><div class="num" id="statPartners">0</div><div class="label">Nhà QC</div></div>
<div class="stat-card"><div class="num" id="statProjects">0</div><div class="label">Tổng dự án</div></div>
<div class="stat-card"><div class="num" id="statDomains">0</div><div class="label">Domain</div></div>
<div class="stat-card"><div class="num" id="statRunning">0</div><div class="label">Đang chạy</div></div>
<div class="stat-card changes" id="statChangesCard" style="display:none"><div class="num" id="statChanges">0</div><div class="label">Thay đổi</div></div>
</div>
<div class="controls">
<input type="text" id="search" placeholder="Tìm tên nhà QC, domain, URL..." oninput="filterData()">
<select id="partnerFilter" onchange="filterData()"><option value="">Tất cả nhà QC</option></select>
<div class="change-filters" id="changeFilters" style="display:none">
<div class="chip chip-all active" onclick="setChangeFilter('all')" id="chipAll">Tất cả</div>
<div class="chip chip-new" onclick="setChangeFilter('new')" id="chipNew">__CHIP_NEW__</div>
<div class="chip chip-changed" onclick="setChangeFilter('changed')" id="chipChanged">__CHIP_CHANGED__</div>
<div class="chip chip-same" onclick="setChangeFilter('same')" id="chipSame">Không đổi</div>
</div>
</div>
</div>
<div class="tabs">
<div class="tab active" onclick="switchView('detail')" id="tabDetail">Chi tiết dự án</div>
<div class="tab" onclick="switchView('summary')" id="tabSummary">Tổng hợp theo nhà QC</div>
</div>
<div class="table-wrap"><table><thead id="tableHead"></thead><tbody id="tableBody"></tbody></table></div>
<div class="modal-overlay" id="partnerModal" onclick="if(event.target===this)closeModal()">
<div class="modal">
<div class="modal-header">
<h2 id="modalTitle"></h2>
<button class="modal-close" onclick="closeModal()">&times;</button>
</div>
<div class="modal-body" id="modalBody"></div>
</div>
</div>
<script>
const rawData=[__DATA__];
const summaryData=[__SUMMARY__];
const removedData=[__REMOVED__];
const hasComparison=__HAS_COMP__;
const partnerHistory=__HISTORY__;
const adsLinks=__ADS_LINKS__;
const uniqueDomains=[...new Set(rawData.map(r=>r.domain))];
document.getElementById('statPartners').textContent=summaryData.length;
document.getElementById('statProjects').textContent=rawData.length;
document.getElementById('statDomains').textContent=uniqueDomains.length;
document.getElementById('statRunning').textContent=rawData.filter(r=>r.status==='Đang chạy').length;
if(hasComparison){
const nc=rawData.filter(r=>r.change==='new').length,cc=rawData.filter(r=>r.change==='changed').length,rc=removedData.length;
document.getElementById('statChangesCard').style.display='block';
document.getElementById('statChanges').textContent=nc+cc+rc;
document.getElementById('changeFilters').style.display='flex';
}
let currentView='detail',sortCol=null,sortAsc=true,changeFilter='all';
function setChangeFilter(f){changeFilter=f;document.querySelectorAll('.chip').forEach(c=>c.classList.remove('active'));document.getElementById({all:'chipAll',new:'chipNew',changed:'chipChanged',same:'chipSame'}[f]).classList.add('active');filterData()}
function switchView(v){currentView=v;document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.getElementById(v==='detail'?'tabDetail':'tabSummary').classList.add('active');filterData()}
function renderHeader(v){const h=document.getElementById('tableHead');if(v==='detail'){const c=hasComparison?'<th>Thay đổi</th>':'';h.innerHTML=`<tr><th>#</th><th onclick="sortBy('partner')">Nhà QC <span class="sort-indicator">↕</span></th><th onclick="sortBy('domain')">Domain <span class="sort-indicator">↕</span></th><th>URL chuẩn hóa</th><th>URL gốc</th><th onclick="sortBy('status')">Trạng thái <span class="sort-indicator">↕</span></th><th onclick="sortBy('last_date')">Ngày cập nhật <span class="sort-indicator">↕</span></th><th>Google Ads Transparency</th>${c}</tr>`}else{const c=hasComparison?`<th onclick="sortBy('new_count')">Mới</th>`:'';h.innerHTML=`<tr><th>#</th><th onclick="sortBy('partner')">Nhà QC <span class="sort-indicator">↕</span></th><th onclick="sortBy('total')">Tổng <span class="sort-indicator">↕</span></th><th onclick="sortBy('running')">Đang chạy <span class="sort-indicator">↕</span></th><th onclick="sortBy('stopped')">Ngưng <span class="sort-indicator">↕</span></th><th onclick="sortBy('domains')">Domain <span class="sort-indicator">↕</span></th><th onclick="sortBy('last_date')">Cập nhật cuối <span class="sort-indicator">↕</span></th><th>Google Ads</th>${c}<th></th></tr>`}}
function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function truncateUrl(u,m){return u.length<=m?u:u.substring(0,m)+'...'}
function copyUrl(url,btn){navigator.clipboard.writeText(url).then(()=>{btn.classList.add('copied');setTimeout(()=>btn.classList.remove('copied'),1500)})}
function closeModal(){document.getElementById('partnerModal').classList.remove('active');document.body.style.overflow=''}
function openPartnerDetail(partner){
const recs=rawData.filter(r=>r.partner===partner);
const hist=partnerHistory[partner]||[];
const adUrl=adsLinks[partner]||'';
const running=recs.filter(r=>r.status==='Đang chạy').length;
const stopped=recs.filter(r=>r.status!=='Đang chạy').length;
const s=new Set(recs.map(r=>r.domain)).size;
let html='';
html+=`<div class="modal-stats"><div class="modal-stat"><div class="num">${recs.length}</div><div class="lbl">Dự án</div></div><div class="modal-stat"><div class="num">${running}</div><div class="lbl">Đang chạy</div></div><div class="modal-stat"><div class="num">${stopped}</div><div class="lbl">Ngưng</div></div><div class="modal-stat"><div class="num">${s}</div><div class="lbl">Domain</div></div></div>`;
if(adUrl)html+=`<div style="margin-bottom:20px"><a href="${escapeHtml(adUrl)}" target="_blank" class="modal-ad-link"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>Google Ads Transparency</a></div>`;
html+=`<div class="modal-section"><h3>Danh sách dự án hiện tại</h3><table class="modal-table"><thead><tr><th>Domain</th><th>URL</th><th>Trạng thái</th><th></th></tr></thead><tbody>`;
recs.forEach(r=>{const b=r.status==='Đang chạy'?'<span class="badge running">Đang chạy</span>':'<span class="badge stopped">Ngưng chạy</span>';
html+=`<tr><td style="font-weight:600;color:#0f3460">${escapeHtml(r.domain)}</td><td><a href="${escapeHtml(r.url_normalized)}" target="_blank">${escapeHtml(r.url_normalized)}</a></td><td>${b}</td><td><button class="copy-btn" onclick="copyUrl('${escapeHtml(r.url_normalized)}',this)" title="Copy URL"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button></td></tr>`});
html+=`</tbody></table></div>`;
if(hist.length>1){
const sorted=[...hist].reverse();
html+=`<div class="modal-section"><h3>Lịch sử thay đổi</h3>`;
sorted.forEach(ev=>{
let badge='',txt='';
if(ev.action==='added'){badge='<span class="badge new">Thêm</span>';txt=`Thêm dự án <span class="timeline-domain">${escapeHtml(ev.domain)}</span>`}
else if(ev.action==='removed'){badge='<span class="badge removed">Xóa</span>';txt=`Xóa dự án <span class="timeline-domain">${escapeHtml(ev.domain)}</span>`}
else if(ev.action==='status_change'){badge='<span class="badge changed">Đổi</span>';txt=`<span class="timeline-domain">${escapeHtml(ev.domain)}</span>: ${escapeHtml(ev.old_status||'')} → ${escapeHtml(ev.status||'')}`}
html+=`<div class="timeline-item"><div class="timeline-date">${escapeHtml(ev.date)}</div><div class="timeline-action">${badge}${txt}</div></div>`});
html+=`</div>`}
else if(hist.length<=1){html+=`<div class="modal-section"><h3>Lịch sử thay đổi</h3><p style="color:#999;font-size:13px">Chưa có lịch sử thay đổi. Cập nhật data vài lần để thấy lịch sử.</p></div>`}
document.getElementById('modalTitle').textContent=partner;
document.getElementById('modalBody').innerHTML=html;
document.getElementById('partnerModal').classList.add('active');
document.body.style.overflow='hidden'}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()})
function filterData(){
const search=document.getElementById('search').value.toLowerCase(),pv=document.getElementById('partnerFilter').value;
renderHeader(currentView);const body=document.getElementById('tableBody');
const colCount=hasComparison?(currentView==='detail'?9:10):(currentView==='detail'?8:9);
if(currentView==='detail'){
let f=rawData.filter(r=>{const ms=!search||r.partner.toLowerCase().includes(search)||r.domain.toLowerCase().includes(search)||r.url_original.toLowerCase().includes(search);const mp=!pv||r.partner===pv;const mc=changeFilter==='all'||(changeFilter==='new'&&r.change==='new')||(changeFilter==='changed'&&r.change==='changed')||(changeFilter==='same'&&(!r.change||r.change==='same'));return ms&&mp&&mc});
if(sortCol)f.sort((a,b)=>{let va=(a[sortCol]||'').toString().toLowerCase(),vb=(b[sortCol]||'').toString().toLowerCase();return va<vb?(sortAsc?-1:1):va>vb?(sortAsc?1:-1):0});
let lp=null,html='',stt=0;
f.forEach(r=>{stt++;if(r.partner!==lp){const c=rawData.filter(x=>x.partner===r.partner).length;html+=`<tr class="partner-group-row"><td colspan="${colCount}">${escapeHtml(r.partner)} <span class="count" style="cursor:pointer;text-decoration:underline" onclick="openPartnerDetail('${escapeHtml(r.partner).replace(/'/g,"\\'")}')">${c} dự án →</span></td></tr>`;lp=r.partner}
const badge=r.status==='Đang chạy'?'<span class="badge running">Đang chạy</span>':'<span class="badge stopped">Ngưng chạy</span>';
let rc='',cb='';if(hasComparison){if(r.change==='new'){rc='row-new';cb='<span class="badge new">Mới</span>'}else if(r.change==='changed'){rc='row-changed';cb=`<span class="badge changed">${escapeHtml(r.old_status||'')} → ${escapeHtml(r.status)}</span>`}else cb='<span style="color:#ccc;font-size:11px">—</span>'}
const cTd=hasComparison?`<td>${cb}</td>`:'';
const ad=`<a href="${escapeHtml(r.ad_library_url)}" target="_blank" class="ad-link"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>Google Ads</a>`;
html+=`<tr class="${rc}"><td style="text-align:center;color:#999;font-size:12px">${stt}</td><td class="partner-cell">${escapeHtml(r.partner)}</td><td class="domain-cell">${escapeHtml(r.domain)}</td><td><span class="url-cell-wrap"><a href="${escapeHtml(r.url_normalized)}" target="_blank">${escapeHtml(r.url_normalized)}</a><button class="copy-btn" onclick="copyUrl('${escapeHtml(r.url_normalized)}',this)" title="Copy URL"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button></span></td><td class="url-orig-cell" title="${escapeHtml(r.url_original)}"><a href="${escapeHtml(r.url_original.startsWith('http')?r.url_original:'https://'+r.url_original)}" target="_blank">${escapeHtml(truncateUrl(r.url_original,50))}</a></td><td>${badge}</td><td style="font-size:12px;color:#666;white-space:nowrap">${escapeHtml(r.last_date||'')}</td><td>${ad}</td>${cTd}</tr>`});
if(hasComparison&&(changeFilter==='all'||changeFilter==='new')){const rf=removedData.filter(r=>{const ms=!search||r.partner.toLowerCase().includes(search)||r.domain.toLowerCase().includes(search);const mp=!pv||r.partner===pv;return ms&&mp});if(rf.length){html+=`<tr class="partner-group-row" style="background:#fce4ec"><td colspan="${colCount}">Đã xóa (${rf.length}) <span class="count" style="background:#e94560">${rf.length} bỏ</span></td></tr>`;rf.forEach(r=>{html+=`<tr style="opacity:.6;text-decoration:line-through"><td></td><td class="partner-cell">${escapeHtml(r.partner)}</td><td class="domain-cell">${escapeHtml(r.domain)}</td><td><a href="${escapeHtml(r.url_normalized)}" target="_blank" style="text-decoration:line-through">${escapeHtml(r.url_normalized)}</a></td><td class="url-orig-cell">${escapeHtml(truncateUrl(r.url_original||r.domain,50))}</td><td><span class="badge removed">Đã xóa</span></td><td>—</td>${hasComparison?'<td><span class="badge removed">Xóa</span></td>':''}</tr>`})}}
if(!html)html=`<tr><td colspan="${colCount}" class="no-results">Không tìm thấy kết quả</td></tr>`;
body.innerHTML=html}else{
let f=summaryData.filter(r=>{const ms=!search||r.partner.toLowerCase().includes(search);const mp=!pv||r.partner===pv;return ms&&mp});
if(sortCol)f.sort((a,b)=>{let va=a[sortCol],vb=b[sortCol];if(typeof va==='string'){va=va.toLowerCase();vb=vb.toString().toLowerCase()}return va<vb?(sortAsc?-1:1):va>vb?(sortAsc?1:-1):0});else f.sort((a,b)=>b.total-a.total);
let html='',stt2=0;f.forEach(r=>{stt2++;const recs=rawData.filter(x=>x.partner===r.partner);const stopped=recs.filter(x=>x.status!=='Đang chạy').length;const domains=new Set(recs.map(x=>x.domain)).size;const lastDate=recs.map(x=>x.last_date||'').filter(Boolean).sort().pop()||'';const adUrl=adsLinks[r.partner]||'';const cTd=hasComparison?`<td>${r.new_count?'<span class="badge new">+'+r.new_count+'</span>':'<span style="color:#ccc">—</span>'}</td>`:'';const adTd=adUrl?`<td><a href="${escapeHtml(adUrl)}" target="_blank" class="ad-link"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>Google Ads</a></td>`:'<td>—</td>';r.stopped=stopped;r.domains=domains;r.last_date=lastDate;html+=`<tr><td style="text-align:center;color:#999;font-size:12px">${stt2}</td><td class="partner-cell">${escapeHtml(r.partner)}</td><td><strong>${r.total}</strong></td><td><span class="badge running">${r.running}</span></td><td>${stopped?'<span class="badge stopped">'+stopped+'</span>':'<span style="color:#ccc">—</span>'}</td><td style="color:#888">${domains}</td><td style="font-size:12px;color:#666;white-space:nowrap">${escapeHtml(lastDate)}</td>${adTd}${cTd}<td><button class="copy-btn" onclick="openPartnerDetail('${escapeHtml(r.partner).replace(/'/g,"\\'")}')" title="Xem chi tiết" style="width:auto;padding:4px 10px;font-size:12px;font-weight:600">Chi tiết →</button></td></tr>`});
if(!html)html=`<tr><td colspan="${colCount}" class="no-results">Không tìm thấy kết quả</td></tr>`;
body.innerHTML=html}}
function sortBy(col){if(sortCol===col)sortAsc=!sortAsc;else{sortCol=col;sortAsc=true}filterData()}
const sel=document.getElementById('partnerFilter');summaryData.forEach(s=>{const o=document.createElement('option');o.value=s.partner;o.textContent=`${s.partner} (${s.total})`;sel.appendChild(o)});
filterData();
</script>
</body>
</html>'''
    
    chip_new = f"Mới thêm ({new_count})" if new_count else "Mới thêm"
    chip_changed = f"Đổi trạng thái ({changed_count})" if changed_count else "Đổi trạng thái"
    
    html = HTML
    html = html.replace("__TIMESTAMP__", timestamp)
    html = html.replace("__COMPARE_INFO__", compare_info)
    html = html.replace("__DATA__", ",\n".join(detail_js))
    html = html.replace("__SUMMARY__", ",\n".join(summary_js))
    html = html.replace("__REMOVED__", ",\n".join(removed_js))
    html = html.replace("__HAS_COMP__", "true" if has_comparison else "false")
    html = html.replace("__HISTORY__", history_js)
    html = html.replace("__ADS_LINKS__", ads_links_js)
    html = html.replace("__CHIP_NEW__", chip_new)
    html = html.replace("__CHIP_CHANGED__", chip_changed)
    return html

# ==================== MAIN ====================

def main():
    # 1. Parse raw data
    records, summary = parse_raw_data(RAW_FILE)
    
    # 2. Load previous snapshot
    snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json")])
    prev_snap = None
    prev_timestamp = ""
    if snapshots:
        with open(os.path.join(SNAPSHOT_DIR, snapshots[-1]), encoding="utf-8") as f:
            prev_data = json.load(f)
        prev_snap = prev_data.get("data", {})
        prev_timestamp = prev_data.get("timestamp", "")
    
    # 3. Detect changes
    # Skip comparison if last snapshot is from same run
    current_snap = build_snapshot(records)
    if snapshots and prev_snap == current_snap:
        has_comparison = False
        removed = []
        for r in records:
            r["change"] = "same"
    else:
        has_comparison, removed = detect_changes(records, prev_snap)
    
    # 4. Timestamp
    now = datetime.now()
    timestamp = now.strftime("%d/%m/%Y %H:%M:%S")
    
    # 4b. Build partner history from all snapshots
    partner_history, last_update = build_partner_history(SNAPSHOT_DIR, records, timestamp)
    
    # 4c. Collect ads links per partner
    ads_links = {}
    for r in records:
        if r.get("ad_library_url"):
            ads_links[r["partner"]] = r["ad_library_url"]
    
    # 5. Build HTML
    html = build_html(records, summary, removed, has_comparison, timestamp, prev_timestamp, partner_history, ads_links, last_update)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    # Also write to deploy folder
    os.makedirs(os.path.dirname(DEPLOY_HTML), exist_ok=True)
    with open(DEPLOY_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    
    # 6. Save snapshot
    snap_file = os.path.join(SNAPSHOT_DIR, f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.json")
    with open(snap_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": timestamp, "data": current_snap}, f, ensure_ascii=False, indent=2)
    
    # 7. Print summary
    new_count = sum(1 for r in records if r.get("change") == "new")
    changed_count = sum(1 for r in records if r.get("change") == "changed")
    
    print("=" * 50)
    print("  QC TRACKER — UPDATE COMPLETE")
    print("=" * 50)
    print(f"  Timestamp:      {timestamp}")
    print(f"  Nhà QC:         {len(summary)}")
    print(f"  Tổng dự án:     {len(records)}")
    print(f"  Domain duy nhất:{len(set(r['domain'] for r in records))}")
    print(f"  Output:         {OUTPUT_HTML}")
    print(f"  Deploy copy:    {DEPLOY_HTML}")
    
    if has_comparison:
        print(f"  So với:         {prev_timestamp}")
        print(f"    Mới:          {new_count}")
        print(f"    Đổi status:   {changed_count}")
        print(f"    Đã xóa:       {len(removed)}")
    else:
        print(f"  (Chưa có snapshot trước để so sánh)")
    
    print(f"  Snapshot:       {snap_file}")
    print("=" * 50)

if __name__ == "__main__":
    main()
