#!/usr/bin/env python3
"""
QC Tracker — Update Script
==========================
Workflow:
  1. Paste raw data (TSV) vào raw_data.txt
  2. Chạy: python3 update.py
  3. File index.html tự sinh → deploy lên Vercel
  4. Data upsert lên Supabase (điền credentials bên dưới)

Tự động:
  - Normalize URL (bỏ UTM, www, tracking params)
  - So sánh với snapshot trước → highlight MỚI / ĐỔI / XÓA
  - Upsert toàn bộ data lên Supabase
  - Ghi timestamp cập nhật
"""

import json
import os
from datetime import datetime
from urllib.parse import quote, urlparse

# ==================== CONFIG ====================
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
RAW_FILE     = os.path.join(BASE_DIR, "raw_data.txt")
SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots")
OUTPUT_HTML  = os.path.join(BASE_DIR, "index.html")
DEPLOY_HTML  = os.path.join(BASE_DIR, "vercel-app", "public", "index.html")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# ==================== SUPABASE CONFIG ====================
# Keys được load từ supabase_config.py (không commit lên git)
try:
    from supabase_config import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY
except ImportError:
    SUPABASE_URL         = "https://your-project.supabase.co"
    SUPABASE_SERVICE_KEY = "YOUR_SERVICE_ROLE_KEY"
    SUPABASE_ANON_KEY    = "YOUR_ANON_KEY"

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
    snapshots = sorted([f for f in os.listdir(snapshot_dir) if f.endswith(".json")])

    timeline = []
    for snap_file in snapshots:
        with open(os.path.join(snapshot_dir, snap_file), encoding="utf-8") as f:
            snap = json.load(f)
        timeline.append({"timestamp": snap.get("timestamp",""), "data": snap.get("data",{})})

    current_map = {}
    for r in current_records:
        current_map[f"{r['partner']}|{r['domain']}"] = r["status"]
    timeline.append({"timestamp": current_timestamp, "data": current_map})

    partner_history = {}
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

    last_update = {}
    for partner, events in partner_history.items():
        for ev in events:
            if ev["action"] in ("added", "status_change"):
                key = f"{partner}|{ev['domain']}"
                last_update[key] = ev["date"]

    return partner_history, last_update

def js_escape(s):
    return str(s).replace("\\","\\\\").replace("'","\\'").replace('"','\\"').replace("\n"," ").replace("\r","")

# ==================== SUPABASE UPSERT ====================

def upsert_to_supabase(records, timestamp):
    if SUPABASE_SERVICE_KEY.startswith("YOUR_"):
        print("  ⚠  Supabase credentials chưa được điền. Bỏ qua upsert.")
        return
    try:
        from supabase import create_client
    except ImportError:
        print("  ⚠  Chưa cài supabase. Chạy: pip install supabase")
        return

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Giữ lại các field do user nhập (duyet, traffic, ghi_chu)
    res = client.table("projects").select("partner,domain,duyet,traffic,ghi_chu").execute()
    user_data = {(r["partner"], r["domain"]): r for r in (res.data or [])}

    deduped = {}
    for r in records:
        key = (r["partner"], r["domain"])
        u = user_data.get(key, {})
        deduped[key] = {
            "partner":        r["partner"],
            "domain":         r["domain"],
            "url_original":   r.get("url_original", ""),
            "url_normalized": r.get("url_normalized", ""),
            "status":         r.get("status", ""),
            "ad_library_url": r.get("ad_library_url", ""),
            "change":         r.get("change", "same"),
            "old_status":     r.get("old_status", ""),
            "last_date":      r.get("last_date", timestamp),
            "duyet":          u.get("duyet", False),
            "traffic":        u.get("traffic", ""),
            "ghi_chu":        u.get("ghi_chu", ""),
        }
    rows = list(deduped.values())

    batch = 500
    for i in range(0, len(rows), batch):
        client.table("projects").upsert(
            rows[i:i+batch], on_conflict="partner,domain"
        ).execute()

    print(f"  Supabase: {len(rows)} records upserted ✓")

# ==================== BUILD HTML ====================

def build_html(records, removed, has_comparison, timestamp, prev_timestamp, partner_history, supabase_url, supabase_anon_key):
    new_count     = sum(1 for r in records if r.get("change") == "new")
    changed_count = sum(1 for r in records if r.get("change") == "changed")

    removed_js = []
    for r in removed:
        removed_js.append('{partner:"%s",domain:"%s",url_normalized:"%s",status:"%s"}' % (
            js_escape(r["partner"]), js_escape(r["domain"]),
            js_escape(r["url_normalized"]), js_escape(r["status"])
        ))

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

    compare_info = f'(so với lần trước: <strong>{prev_timestamp}</strong>)' if has_comparison and prev_timestamp else ""
    chip_new     = f"Mới thêm ({new_count})" if new_count else "Mới thêm"
    chip_changed = f"Đổi trạng thái ({changed_count})" if changed_count else "Đổi trạng thái"

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
.table-wrap{background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.08);max-height:calc(100vh - 270px);overflow-x:auto;overflow-y:auto}
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
.badge.duyet{background:#d4edda;color:#155724}
.partner-cell{font-weight:600;color:#16213e}
.domain-cell{color:#888;font-size:12px}
.url-orig-cell{color:#aaa;font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
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
/* Partner modal */
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
.proj-timeline{display:flex;flex-direction:column;gap:4px;padding:4px 0}
.proj-ev{display:flex;align-items:center;gap:8px;font-size:12px;padding:3px 0}
.proj-ev-date{color:#888;min-width:130px;font-weight:600;white-space:nowrap}
.proj-ev-icon{width:20px;height:20px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.ev-add .proj-ev-icon{background:#d4edda;color:#155724}
.ev-remove .proj-ev-icon{background:#f8d7da;color:#721c24}
.ev-change .proj-ev-icon{background:#fff3cd;color:#856404}
.proj-ev-text{color:#333}
.modal-table tr[onclick]:hover{background:#eef2f6!important;cursor:pointer}
.top-bar{display:flex;align-items:center;gap:16px;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap}
.top-bar .stats{margin-bottom:0}
.top-bar .controls{margin-bottom:0}
.change-filters{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.chip{padding:5px 12px;border-radius:20px;font-size:12px;cursor:pointer;border:2px solid transparent;background:#fff;transition:all .2s}
.change-filters{display:flex;gap:6px;justify-content:center;margin-bottom:0;flex-wrap:wrap}
/* Edit modal */
.edit-modal{background:#fff;border-radius:16px;width:100%;max-width:460px;box-shadow:0 20px 60px rgba(0,0,0,.3);overflow:hidden}
.partner-suggest{position:absolute;top:0;left:0;right:0;max-height:200px;overflow-y:auto;background:#fff;border:1px solid #ddd;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:100}
.partner-suggest-item{padding:8px 12px;font-size:13px;cursor:pointer;border-bottom:1px solid #f0f0f0}
.partner-suggest-item:hover{background:#eef2f7}
.partner-suggest-item:last-child{border-bottom:none}
.edit-field{margin-bottom:14px}
.edit-field label{display:block;font-size:11px;font-weight:700;color:#16213e;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
.edit-field input[type=text]{width:100%;padding:9px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none;transition:border-color .2s}
.edit-field input[type=text]:focus{border-color:#0f3460}
.edit-checkbox-row{display:flex;align-items:center;gap:10px;padding:6px 0}
.edit-checkbox-row input[type=checkbox]{width:18px;height:18px;cursor:pointer;accent-color:#0f3460}
.edit-checkbox-row span{font-size:13px;color:#333}
.edit-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:20px;padding-top:16px;border-top:1px solid #f0f0f0}
.btn-save{padding:8px 22px;background:#0f3460;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:background .2s}
.btn-save:hover:not(:disabled){background:#16213e}
.btn-save:disabled{background:#aaa;cursor:not-allowed}
.btn-cancel{padding:8px 16px;background:#f0f2f5;color:#333;border:none;border-radius:8px;font-size:13px;cursor:pointer}
/* Camp filters */
.camp-filters{display:flex;gap:6px;justify-content:center;margin-bottom:10px;flex-wrap:wrap}
.camp-chip{padding:5px 14px;border-radius:20px;font-size:12px;cursor:pointer;border:2px solid #ddd;background:#fff;transition:all .2s}
.camp-chip.active{background:#0f3460;color:#fff;border-color:#0f3460}
/* Affiliate rows */
.aff-domain-row{background:#eef2f7;cursor:pointer}
.aff-domain-row:hover{background:#dce8f5}
.aff-sub-input{width:200px;padding:3px 7px;border:1px solid #ddd;border-radius:4px;font-size:12px;outline:none}
.aff-sub-input:focus{border-color:#0f3460}
.aff-sub-textarea{width:240px;min-height:52px;padding:3px 7px;border:1px solid #ddd;border-radius:4px;font-size:12px;outline:none;resize:vertical;font-family:inherit;word-break:break-all}
.aff-sub-textarea:focus{border-color:#0f3460}
.aff-sub-select{padding:3px 7px;border:1px solid #ddd;border-radius:4px;font-size:12px;background:#fff;outline:none}
.btn-del-row{padding:2px 8px;font-size:11px;background:#fee;color:#e94560;border:1px solid #f5c6cb;border-radius:4px;cursor:pointer}
.btn-add-acc{padding:5px 14px;font-size:12px;font-weight:600;background:#0f3460;color:#fff;border:none;border-radius:6px;cursor:pointer;margin:6px 0 6px 28px}
.btn-add-acc:hover{background:#16213e}
</style>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
</head>
<body>
<h1>Danh sách nhà QC &amp; Dự án</h1>
<p class="subtitle">Dữ liệu đã chuẩn hóa</p>
<p class="update-time">Cập nhật lúc: <strong id="updateTime">__TIMESTAMP__</strong> <span id="compareInfo" style="margin-left:16px;color:#e94560">__COMPARE_INFO__</span></p>
<div class="top-bar">
<div class="stats">
<div class="stat-card"><div class="num" id="statPartners">—</div><div class="label">Nhà QC</div></div>
<div class="stat-card"><div class="num" id="statProjects">—</div><div class="label">Tổng dự án</div></div>
<div class="stat-card"><div class="num" id="statDomains">—</div><div class="label">Domain</div></div>
<div class="stat-card"><div class="num" id="statRunning">—</div><div class="label">Đang chạy</div></div>
<div class="stat-card changes" id="statChangesCard" style="display:none"><div class="num" id="statChanges">0</div><div class="label">Thay đổi</div></div>
</div>
<div class="controls">
<input type="text" id="search" placeholder="Tìm tên nhà QC, domain, URL..." oninput="filterData()">
<select id="partnerFilter" onchange="filterData()"><option value="">Tất cả nhà QC</option></select>
<select id="duyetFilter" onchange="filterData()"><option value="">Duyệt: Tất cả</option><option value="1">Đã duyệt</option><option value="0">Chưa duyệt</option></select>
<button id="refreshBtn" onclick="refreshData()" style="padding:6px 14px;background:#0f3460;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:500">↻ Làm mới</button>
<button id="addBtn" onclick="openAddModal()" style="padding:6px 14px;background:#28a745;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:500">+ Thêm dự án</button>
<button id="addAffBtn" onclick="openAddModal(true)" style="display:none;padding:6px 14px;background:#28a745;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:500">+ Thêm dự án (đã duyệt)</button>
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
<div class="tab" onclick="switchView('affiliate')" id="tabAffiliate">Affiliate</div>
<div class="tab" onclick="switchView('camp')" id="tabCamp">Camp</div>
<div class="tab" onclick="switchView('summary')" id="tabSummary">Tổng hợp theo nhà QC</div>
</div>
<div class="camp-filters" id="campFilters" style="display:none">
<div class="camp-chip active" onclick="setCampFilter('all')" id="campAll">Tất cả</div>
<div class="camp-chip" onclick="setCampFilter('Đang chạy')" id="campRunning">Đang chạy</div>
<div class="camp-chip" onclick="setCampFilter('Tạm ngưng')" id="campPaused">Tạm ngưng</div>
<div class="camp-chip" onclick="setCampFilter('Bỏ')" id="campStopped">Bỏ</div>
</div>
<div class="table-wrap"><table><thead id="tableHead"></thead><tbody id="tableBody"></tbody></table></div>

<!-- Partner detail modal -->
<div class="modal-overlay" id="partnerModal" onclick="if(event.target===this)closeModal()">
<div class="modal">
<div class="modal-header"><h2 id="modalTitle"></h2><button class="modal-close" onclick="closeModal()">&times;</button></div>
<div class="modal-body" id="modalBody"></div>
</div>
</div>

<!-- Edit modal (Duyệt / Traffic / Ghi chú) -->
<div class="modal-overlay" id="editModal" onclick="if(event.target===this)closeEditModal()">
<div class="edit-modal">
<div class="modal-header"><h2 id="editModalTitle">Chỉnh sửa</h2><button class="modal-close" onclick="closeEditModal()">&times;</button></div>
<div class="modal-body" style="padding:20px 24px">
<div class="edit-field">
  <label>Duyệt (đưa vào tab Affiliate)</label>
  <div class="edit-checkbox-row"><input type="checkbox" id="editDuyet"><span>Dự án này đã được duyệt để đăng ký Affiliate</span></div>
</div>
<div class="edit-field"><label>Traffic</label><input type="text" id="editTraffic" placeholder="Điền thông tin traffic..."></div>
<div class="edit-field"><label>Ghi chú</label><input type="text" id="editGhiChu" placeholder="Ghi chú..."></div>
<div class="edit-field"><label>Chính sách Ads</label><select id="editAdsPolicy" style="width:100%;padding:9px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none"><option value="">Chưa xác định</option><option value="Cho chạy Ads">Cho chạy Ads</option><option value="Cấm Brand">Cấm Brand</option><option value="Cấm SEM">Cấm SEM</option><option value="Cấm hoàn toàn">Cấm hoàn toàn</option></select></div>
<div class="edit-field"><label>Traffic Type</label><select id="editTrafficType" style="width:100%;padding:9px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none" onchange="document.getElementById('editDurationField').style.display=this.value==='Recurring'?'block':'none'"><option value="">Chưa xác định</option><option value="Recurring">Recurring</option><option value="One-time">One-time</option><option value="Lifetime">Lifetime</option></select></div>
<div class="edit-field" id="editDurationField" style="display:none"><label>Thời hạn (Recurring)</label><input type="text" id="editTrafficDuration" placeholder="VD: 30 ngày, 3 tháng..."></div>
<div class="edit-field"><label>Cookies</label><input type="text" id="editCookies" placeholder="Thời hạn cookies..."></div>
<div class="edit-field"><label>% Hoa hồng</label><input type="text" id="editHoaHong" placeholder="VD: 30%, 50%..."></div>
<div class="edit-actions">
<button class="btn-cancel" onclick="closeEditModal()">Hủy</button>
<button class="btn-del" onclick="deleteProject()" style="padding:8px 16px;background:#e94560;color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer">Xóa</button>
<button class="btn-save" id="editSaveBtn" onclick="saveEdit()">Lưu</button>
</div>
</div>
</div>
</div>

<!-- Add project modal -->
<div class="modal-overlay" id="addModal" onclick="if(event.target===this)closeAddModal()">
<div class="edit-modal">
<div class="modal-header"><h2>Thêm dự án mới</h2><button class="modal-close" onclick="closeAddModal()">&times;</button></div>
<div class="modal-body" style="padding:20px 24px">
<div class="edit-field"><label>Nhà QC (Partner) *</label><input type="text" id="addPartner" placeholder="Tên nhà quảng cáo..." autocomplete="off" oninput="handlePartnerInput(this.value)" onfocus="showPartnerSuggestions()" onblur="setTimeout(()=>hidePartnerSuggestions(),200)"><div id="partnerSuggestions" style="display:none;position:relative"></div></div>
<div class="edit-field"><label>URL *</label><input type="text" id="addUrl" placeholder="https://example.com" oninput="previewDomain()"></div>
<div class="edit-field" id="addDomainPreview" style="display:none"><label>Domain (tự động)</label><div style="padding:9px 12px;background:#f0f2f5;border-radius:8px;font-size:13px;color:#0f3460;font-weight:600" id="addDomainText"></div></div>
<div class="edit-field"><label>Trạng thái</label><select id="addStatus" style="width:100%;padding:9px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none"><option value="Đang chạy">Đang chạy</option><option value="Ngưng chạy">Ngưng chạy</option></select></div>
<div class="edit-field"><label>Duyệt Affiliate</label><div class="edit-checkbox-row"><input type="checkbox" id="addDuyet"><span>Tự động đưa vào tab Affiliate</span></div></div>
<div class="edit-field"><label>Google Ads Link (tùy chọn)</label><input type="text" id="addAdLibrary" placeholder="https://adstransparency.google.com/..."></div>
<div class="edit-actions">
<button class="btn-cancel" onclick="closeAddModal()">Hủy</button>
<button class="btn-save" id="addSaveBtn" onclick="saveAddProject()">Thêm</button>
</div>
</div>
</div>
</div>

<script>
const SUPABASE_URL='__SUPABASE_URL__';
const SUPABASE_ANON_KEY='__SUPABASE_ANON_KEY__';
const {createClient}=supabase;
const _sb=createClient(SUPABASE_URL,SUPABASE_ANON_KEY);

// Embedded by Python (comparison metadata - not in Supabase)
const removedData=[__REMOVED__];
const hasComparison=__HAS_COMP__;
const partnerHistory=__HISTORY__;

// App state
let rawData=[],summaryData=[],adsLinks={},affiliateAccounts=[];
let currentView='detail',sortCol=null,sortAsc=true,changeFilter='all';
let campFilter='all',expandedDomains=new Set(),editingRow=null;

// Compute helpers
function computeSummary(data){
  const m={};
  data.forEach(r=>{
    if(!m[r.partner])m[r.partner]={partner:r.partner,total:0,running:0,new_count:0};
    m[r.partner].total++;
    if(r.status==='Đang chạy')m[r.partner].running++;
    if(r.change==='new')m[r.partner].new_count++;
  });
  return Object.values(m);
}
function computeAdsLinks(data){
  const l={};
  data.forEach(r=>{if(r.ad_library_url)l[r.partner]=r.ad_library_url;});
  return l;
}

// Load from Supabase
async function loadAffiliateAccounts(){
  const{data}=await _sb.from('affiliate_accounts').select('*').order('created_at');
  affiliateAccounts=data||[];
}

async function loadData(){
  document.getElementById('tableBody').innerHTML='<tr><td colspan="12" style="text-align:center;padding:40px;color:#999">Đang tải dữ liệu...</td></tr>';
  const{data,error}=await _sb.from('projects').select('*');
  if(error){
    document.getElementById('tableBody').innerHTML='<tr><td colspan="12" style="text-align:center;padding:40px;color:#e94560">Lỗi tải dữ liệu: '+error.message+'</td></tr>';
    return;
  }
  rawData=data||[];
  summaryData=computeSummary(rawData);
  adsLinks=computeAdsLinks(rawData);
  await loadAffiliateAccounts();
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
  const sel=document.getElementById('partnerFilter');
  sel.innerHTML='<option value="">Tất cả nhà QC</option>';
  summaryData.forEach(s=>{const o=document.createElement('option');o.value=s.partner;o.textContent=`${s.partner} (${s.total})`;sel.appendChild(o)});
  filterData();
}

// Tab switching
const tabIds={detail:'tabDetail',summary:'tabSummary',affiliate:'tabAffiliate',camp:'tabCamp'};
async function switchView(v){
  currentView=v;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(tabIds[v]).classList.add('active');
  document.getElementById('campFilters').style.display=v==='camp'?'flex':'none';
  document.getElementById('addBtn').style.display=v==='detail'?'inline-block':'none';
  document.getElementById('addAffBtn').style.display=v==='affiliate'?'inline-block':'none';
  if(v==='camp'||v==='affiliate') await loadAffiliateAccounts();
  filterData();
}
async function refreshData(){
  const btn=document.getElementById('refreshBtn');
  btn.textContent='⏳ Đang tải...';btn.disabled=true;
  await loadData();
  btn.textContent='↻ Làm mới';btn.disabled=false;
}
function setChangeFilter(f){changeFilter=f;document.querySelectorAll('.chip').forEach(c=>c.classList.remove('active'));document.getElementById({all:'chipAll',new:'chipNew',changed:'chipChanged',same:'chipSame'}[f]).classList.add('active');filterData()}
function setCampFilter(f){
  campFilter=f;
  document.querySelectorAll('.camp-chip').forEach(c=>c.classList.remove('active'));
  document.getElementById({all:'campAll','Đang chạy':'campRunning','Tạm ngưng':'campPaused','Bỏ':'campStopped'}[f]).classList.add('active');
  filterData();
}

// Render header
function renderHeader(v){
  const h=document.getElementById('tableHead');
  if(v==='detail'){
    const c=hasComparison?'<th>Thay đổi</th>':'';
    h.innerHTML=`<tr><th>#</th><th onclick="sortBy('partner')">Nhà QC <span class="sort-indicator">↕</span></th><th onclick="sortBy('domain')">Domain <span class="sort-indicator">↕</span></th><th>URL chuẩn hóa</th><th>URL gốc</th><th onclick="sortBy('status')">Trạng thái <span class="sort-indicator">↕</span></th><th onclick="sortBy('last_date')">Ngày cập nhật <span class="sort-indicator">↕</span></th><th>Google Ads</th><th onclick="sortBy('duyet')" style="cursor:pointer">Duyệt <span class="sort-indicator">↕</span></th><th onclick="sortBy('traffic')" style="cursor:pointer">Traffic <span class="sort-indicator">↕</span></th><th>Ghi chú</th><th onclick="sortBy('ads_policy')" style="cursor:pointer">Chính sách Ads <span class="sort-indicator">↕</span></th><th onclick="sortBy('traffic_type')" style="cursor:pointer">Traffic Type <span class="sort-indicator">↕</span></th><th>Cookies</th><th onclick="sortBy('hoa_hong')" style="cursor:pointer">% Hoa hồng <span class="sort-indicator">↕</span></th>${c}</tr>`;
  }else if(v==='summary'){
    const c=hasComparison?`<th onclick="sortBy('new_count')">Mới</th>`:'';
    h.innerHTML=`<tr><th>#</th><th onclick="sortBy('partner')">Nhà QC <span class="sort-indicator">↕</span></th><th onclick="sortBy('total')">Tổng <span class="sort-indicator">↕</span></th><th onclick="sortBy('running')">Đang chạy <span class="sort-indicator">↕</span></th><th onclick="sortBy('stopped')">Ngưng <span class="sort-indicator">↕</span></th><th onclick="sortBy('domains')">Domain <span class="sort-indicator">↕</span></th><th onclick="sortBy('last_date')">Cập nhật cuối <span class="sort-indicator">↕</span></th><th>Google Ads</th>${c}<th></th></tr>`;
  }else if(v==='affiliate'){
    h.innerHTML=`<tr><th style="width:32px"></th><th>#</th><th>Domain</th><th>Partner</th><th>Accounts</th><th>Traffic</th><th>Ghi chú</th><th>Chính sách Ads</th><th>Cookies</th></tr>`;
  }else if(v==='camp'){
    h.innerHTML=`<tr><th>#</th><th>Domain</th><th>Account</th><th>Loại TK Google</th><th>Status Camp</th><th>Affiliate Link</th><th>Landing Page</th><th>Note</th><th>Thông tin thanh toán</th></tr>`;
  }
}

// Escape helpers
function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function truncateUrl(u,m){return u.length<=m?u:u.substring(0,m)+'...'}
function copyUrl(url,btn){navigator.clipboard.writeText(url).then(()=>{btn.classList.add('copied');setTimeout(()=>btn.classList.remove('copied'),1500)})}

// ── Partner detail modal (existing) ──
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
  html+=`<div class="modal-section"><h3>Danh sách dự án &amp; lịch sử từng dự án</h3><table class="modal-table"><thead><tr><th>Domain</th><th>URL</th><th>Trạng thái</th><th></th></tr></thead><tbody>`;
  recs.forEach((r,idx)=>{const b=r.status==='Đang chạy'?'<span class="badge running">Đang chạy</span>':'<span class="badge stopped">Ngưng chạy</span>';
  const projHist=hist.filter(ev=>ev.domain===r.domain);
  html+=`<tr id="proj-${idx}" style="cursor:pointer" onclick="toggleProjHistory(${idx})"><td style="font-weight:600;color:#0f3460">${escapeHtml(r.domain)}${projHist.length>1?' <span style="font-size:10px;color:#1a73e8">('+projHist.length+' events)</span>':''}</td><td><a href="${escapeHtml(r.url_normalized)}" target="_blank" onclick="event.stopPropagation()">${escapeHtml(r.url_normalized)}</a></td><td>${b}</td><td><button class="copy-btn" onclick="copyUrl('${escapeHtml(r.url_normalized)}',this);event.stopPropagation()" title="Copy URL"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button></td></tr>`;
  if(projHist.length>=1){const sorted=[...projHist].reverse();html+=`<tr id="projhist-${idx}" style="display:none;background:#f7f9fc"><td colspan="4" style="padding:8px 12px 8px 32px"><div class="proj-timeline">`;sorted.forEach(ev=>{let ic='',cls='';if(ev.action==='added'){ic='+';cls='ev-add'}else if(ev.action==='removed'){ic='×';cls='ev-remove'}else if(ev.action==='status_change'){ic='→';cls='ev-change'}html+=`<div class="proj-ev ${cls}"><span class="proj-ev-date">${escapeHtml(ev.date)}</span><span class="proj-ev-icon">${ic}</span><span class="proj-ev-text">${ev.action==='added'?'Thêm mới':ev.action==='removed'?'Đã xóa':escapeHtml(ev.old_status||'')+' → '+escapeHtml(ev.status||'')}</span></div>`});html+=`</div></td></tr>`}});
  html+=`</tbody></table></div>`;
  if(hist.length>1){const sortedAll=[...hist].reverse();html+=`<div class="modal-section"><h3>Tổng quan lịch sử thay đổi</h3>`;sortedAll.forEach(ev=>{let badge='',txt='';if(ev.action==='added'){badge='<span class="badge new">Thêm</span>';txt=`Thêm dự án <span class="timeline-domain">${escapeHtml(ev.domain)}</span>`}else if(ev.action==='removed'){badge='<span class="badge removed">Xóa</span>';txt=`Xóa dự án <span class="timeline-domain">${escapeHtml(ev.domain)}</span>`}else if(ev.action==='status_change'){badge='<span class="badge changed">Đổi</span>';txt=`<span class="timeline-domain">${escapeHtml(ev.domain)}</span>: ${escapeHtml(ev.old_status||'')} → ${escapeHtml(ev.status||'')}`}html+=`<div class="timeline-item"><div class="timeline-date">${escapeHtml(ev.date)}</div><div class="timeline-action">${badge}${txt}</div></div>`});html+=`</div>`}else{html+=`<div class="modal-section"><h3>Tổng quan lịch sử thay đổi</h3><p style="color:#999;font-size:13px">Chưa có lịch sử thay đổi. Cập nhật data vài lần để thấy lịch sử.</p></div>`}
  document.getElementById('modalTitle').textContent=partner;
  document.getElementById('modalBody').innerHTML=html;
  document.getElementById('partnerModal').classList.add('active');
  document.body.style.overflow='hidden';
}
function toggleProjHistory(idx){const row=document.getElementById('projhist-'+idx);if(row.style.display==='none'){row.style.display='table-row'}else{row.style.display='none'}}

// ── Edit modal (Duyệt / Traffic / Ghi chú) ──
function openEditModal(partner,domain,e){
  e&&e.stopPropagation();
  const r=rawData.find(x=>x.partner===partner&&x.domain===domain);
  if(!r)return;
  editingRow={partner,domain};
  document.getElementById('editModalTitle').textContent=domain;
  document.getElementById('editDuyet').checked=r.duyet||false;
  document.getElementById('editTraffic').value=r.traffic||'';
  document.getElementById('editGhiChu').value=r.ghi_chu||'';
  document.getElementById('editAdsPolicy').value=r.ads_policy||'';
  document.getElementById('editTrafficType').value=r.traffic_type||'';
  document.getElementById('editTrafficDuration').value=r.traffic_duration||'';
  document.getElementById('editDurationField').style.display=r.traffic_type==='Recurring'?'block':'none';
  document.getElementById('editCookies').value=r.cookies||'';
  document.getElementById('editHoaHong').value=r.hoa_hong||'';
  document.getElementById('editModal').classList.add('active');
  document.body.style.overflow='hidden';
}
function closeEditModal(){document.getElementById('editModal').classList.remove('active');document.body.style.overflow='';editingRow=null;}
async function saveEdit(){
  if(!editingRow)return;
  const btn=document.getElementById('editSaveBtn');
  btn.textContent='Đang lưu...';btn.disabled=true;
  const updates={duyet:document.getElementById('editDuyet').checked,traffic:document.getElementById('editTraffic').value.trim(),ghi_chu:document.getElementById('editGhiChu').value.trim(),ads_policy:document.getElementById('editAdsPolicy').value,traffic_type:document.getElementById('editTrafficType').value,traffic_duration:document.getElementById('editTrafficDuration').value.trim(),cookies:document.getElementById('editCookies').value.trim(),hoa_hong:document.getElementById('editHoaHong').value.trim()};
  const{error}=await _sb.from('projects').update(updates).eq('partner',editingRow.partner).eq('domain',editingRow.domain);
  btn.textContent='Lưu';btn.disabled=false;
  if(error){alert('Lỗi lưu: '+error.message);return;}
  const idx=rawData.findIndex(x=>x.partner===editingRow.partner&&x.domain===editingRow.domain);
  if(idx>=0)Object.assign(rawData[idx],updates);
  closeEditModal();
  filterData();
}

// ── Add new project ──
function normalizeUrlJs(raw){
  if(!raw||!raw.trim())return{domain:'',clean:''};
  let url=raw.trim();
  if(!url.startsWith('http'))url='https://'+url;
  try{
    const p=new URL(url);
    let domain=p.hostname.toLowerCase();
    if(domain.startsWith('www.'))domain=domain.slice(4);
    return{domain,clean:'https://'+domain};
  }catch(e){return{domain:url,clean:url}}
}
function previewDomain(){
  const raw=document.getElementById('addUrl').value;
  const{domain}=normalizeUrlJs(raw);
  const el=document.getElementById('addDomainPreview'),txt=document.getElementById('addDomainText');
  if(domain){el.style.display='block';txt.textContent=domain}else{el.style.display='none'}
}
function openAddModal(autoDuyet){
  document.getElementById('addPartner').value='';
  document.getElementById('addUrl').value='';
  document.getElementById('addStatus').value='Đang chạy';
  document.getElementById('addDuyet').checked=!!autoDuyet;
  document.getElementById('addAdLibrary').value='';
  document.getElementById('addDomainPreview').style.display='none';
  document.getElementById('partnerSuggestions').style.display='none';
  document.getElementById('addModal').classList.add('active');
  document.body.style.overflow='hidden';
}
function getAllPartners(){return [...new Set(rawData.map(r=>r.partner))].sort()}
function handlePartnerInput(val){
  showPartnerSuggestions(val);
}
function showPartnerSuggestions(filter){
  const box=document.getElementById('partnerSuggestions');
  const val=(filter!==undefined?filter:document.getElementById('addPartner').value).toLowerCase().trim();
  if(!val){box.style.display='none';return}
  const all=getAllPartners();
  const matches=all.filter(p=>p.toLowerCase().includes(val)).slice(0,8);
  if(!matches.length){box.style.display='none';return}
  box.innerHTML=matches.map(p=>`<div class="partner-suggest-item" onclick="selectPartner('${p.replace(/'/g,"\\'")}')">${escapeHtml(p)}</div>`).join('');
  box.style.display='block';
}
function hidePartnerSuggestions(){document.getElementById('partnerSuggestions').style.display='none'}
function selectPartner(name){
  document.getElementById('addPartner').value=name;
  hidePartnerSuggestions();
  document.getElementById('addUrl').focus();
}
function closeAddModal(){document.getElementById('addModal').classList.remove('active');document.body.style.overflow='';}
async function saveAddProject(){
  const partner=document.getElementById('addPartner').value.trim();
  const rawUrl=document.getElementById('addUrl').value.trim();
  if(!partner){alert('Vui lòng nhập tên nhà QC');return;}
  if(!rawUrl){alert('Vui lòng nhập URL');return;}
  const{domain,clean}=normalizeUrlJs(rawUrl);
  if(!domain){alert('URL không hợp lệ');return;}
  const btn=document.getElementById('addSaveBtn');
  btn.textContent='Đang thêm...';btn.disabled=true;
  const timestamp=new Date().toLocaleDateString('en-GB').replace(/\//g,'-')+' '+new Date().toLocaleTimeString('en-GB');
  const row={partner,domain,url_original:rawUrl,url_normalized:clean,status:document.getElementById('addStatus').value,ad_library_url:document.getElementById('addAdLibrary').value.trim(),change:'new',old_status:'',last_date:timestamp,duyet:document.getElementById('addDuyet').checked,traffic:'',ghi_chu:'',ads_policy:'',traffic_type:'',traffic_duration:'',cookies:'',hoa_hong:''};
  const{data,error}=await _sb.from('projects').upsert(row,{onConflict:'partner,domain'}).select().single();
  btn.textContent='Thêm';btn.disabled=false;
  if(error){alert('Lỗi: '+error.message);return;}
  rawData.push(data||row);
  summaryData=computeSummary(rawData);
  adsLinks=computeAdsLinks(rawData);
  const sel=document.getElementById('partnerFilter');
  sel.innerHTML='<option value="">Tất cả nhà QC</option>';
  summaryData.forEach(s=>{const o=document.createElement('option');o.value=s.partner;o.textContent=`${s.partner} (${s.total})`;sel.appendChild(o)});
  const uniqueDomains=[...new Set(rawData.map(r=>r.domain))];
  document.getElementById('statPartners').textContent=summaryData.length;
  document.getElementById('statProjects').textContent=rawData.length;
  document.getElementById('statDomains').textContent=uniqueDomains.length;
  document.getElementById('statRunning').textContent=rawData.filter(r=>r.status==='Đang chạy').length;
  closeAddModal();
  filterData();
}
async function deleteProject(){
  if(!editingRow)return;
  if(!confirm('Xóa dự án này khỏi hệ thống?'))return;
  const{error}=await _sb.from('projects').delete().eq('partner',editingRow.partner).eq('domain',editingRow.domain);
  if(error){alert('Lỗi: '+error.message);return;}
  rawData=rawData.filter(r=>!(r.partner===editingRow.partner&&r.domain===editingRow.domain));
  summaryData=computeSummary(rawData);
  adsLinks=computeAdsLinks(rawData);
  closeEditModal();
  filterData();
}

// ── Affiliate tab ──
function renderAffiliate(){
  renderHeader('affiliate');
  const body=document.getElementById('tableBody');
  const list=rawData.filter(r=>r.duyet);
  if(!list.length){body.innerHTML='<tr><td colspan="9" class="no-results">Chưa có dự án nào được duyệt.<br>Vào tab <strong>Chi tiết dự án</strong> → click vào hàng → tick Duyệt.</td></tr>';return;}
  let html='',affStt=0;
  list.forEach(r=>{
    affStt++;
    const key=r.partner+'|'+r.domain;
    const accs=affiliateAccounts.filter(a=>a.partner===r.partner&&a.domain===r.domain);
    const isExp=expandedDomains.has(key);
    const pe=r.partner.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
    const de=r.domain.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
    html+=`<tr class="aff-domain-row" onclick="toggleDomain('${pe}','${de}')">
      <td style="text-align:center;color:#0f3460;font-size:14px">${isExp?'▼':'▶'}</td>
      <td style="text-align:center;color:#999;font-size:12px">${affStt}</td>
      <td><strong style="color:#0f3460">${escapeHtml(r.domain)}</strong></td>
      <td style="color:#888;font-size:12px">${escapeHtml(r.partner)}</td>
      <td style="font-size:12px">${accs.length?'<span style="color:#0f3460;font-weight:600">'+accs.length+' accounts</span>':'<span style="color:#ccc">—</span>'}</td>
      <td onclick="event.stopPropagation()"><textarea class="aff-sub-textarea" style="width:160px;min-height:38px" onblur="updateProjectField('${pe}','${de}','traffic',this.value)" placeholder="Traffic...">${escapeHtml(r.traffic||'')}</textarea></td>
      <td onclick="event.stopPropagation()"><textarea class="aff-sub-textarea" style="width:160px;min-height:38px" onblur="updateProjectField('${pe}','${de}','ghi_chu',this.value)" placeholder="Ghi chú...">${escapeHtml(r.ghi_chu||'')}</textarea></td>
      <td onclick="event.stopPropagation()"><select class="aff-sub-select" onchange="updateProjectField('${pe}','${de}','ads_policy',this.value)"><option value=""${!r.ads_policy?' selected':''}>—</option><option value="Cho chạy Ads"${r.ads_policy==='Cho chạy Ads'?' selected':''}>Cho chạy Ads</option><option value="Cấm Brand"${r.ads_policy==='Cấm Brand'?' selected':''}>Cấm Brand</option><option value="Cấm SEM"${r.ads_policy==='Cấm SEM'?' selected':''}>Cấm SEM</option><option value="Cấm hoàn toàn"${r.ads_policy==='Cấm hoàn toàn'?' selected':''}>Cấm hoàn toàn</option></select></td>
      <td onclick="event.stopPropagation()"><input class="aff-sub-input" style="width:160px" value="${escapeHtml(r.cookies||'')}" placeholder="Cookies..." onblur="updateProjectField('${pe}','${de}','cookies',this.value)"></td>
    </tr>`;
    if(isExp){
      if(accs.length){
        html+=`<tr><td colspan="9" style="padding:0 0 0 28px;background:#fafbfc">
<table style="width:100%;border-collapse:collapse;font-size:12px">
<thead><tr style="background:#eef2f7">
<th style="padding:6px 8px;font-weight:600;color:#16213e">#</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Status đăng ký</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Dashboard</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Affiliate Link</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Account</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Landing Page</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Loại TK Google</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Status Camp</th>
<th style="padding:6px 8px;font-weight:600;color:#16213e">Note</th>
<th></th>
</tr></thead><tbody>`;
        accs.forEach((a,ai)=>{
          html+=`<tr style="border-bottom:1px solid #f0f0f0">
<td style="padding:5px 8px;color:#999">${ai+1}</td>
<td style="padding:4px 8px"><select class="aff-sub-select" onchange="updateAffField(${a.id},'status',this.value)">
${['Đã xin','Duyệt','Từ chối'].map(s=>`<option${a.status===s?' selected':''}>${s}</option>`).join('')}
</select></td>
<td style="padding:4px 8px"><textarea class="aff-sub-textarea" onblur="updateAffField(${a.id},'dashboard_url',this.value)" placeholder="URL dashboard...">${escapeHtml(a.dashboard_url||'')}</textarea></td>
<td style="padding:4px 8px"><textarea class="aff-sub-textarea" onblur="updateAffField(${a.id},'affiliate_link',this.value)" placeholder="Affiliate link...">${escapeHtml(a.affiliate_link||'')}</textarea></td>
<td style="padding:4px 8px"><input class="aff-sub-input" value="${escapeHtml(a.account||'')}" onblur="updateAffField(${a.id},'account',this.value)" placeholder="email@..."></td>
<td style="padding:4px 8px"><textarea class="aff-sub-textarea" onblur="updateAffField(${a.id},'landing_page',this.value)" placeholder="Landing page...">${escapeHtml(a.landing_page||'')}</textarea></td>
<td style="padding:4px 8px"><input class="aff-sub-input" value="${escapeHtml(a.loai_tk_google||'')}" onblur="updateAffField(${a.id},'loai_tk_google',this.value)" placeholder="Loại TK..."></td>
<td style="padding:4px 8px"><select class="aff-sub-select" onchange="updateAffField(${a.id},'camp_status',this.value)">
<option value=""${!a.camp_status?' selected':''}>Chưa lên camp</option>
${['Đang chạy','Tạm ngưng','Bỏ'].map(s=>`<option${a.camp_status===s?' selected':''}>${s}</option>`).join('')}
</select></td>
<td style="padding:4px 8px"><textarea class="aff-sub-textarea" onblur="updateAffField(${a.id},'note',this.value)" placeholder="Ghi chú...">${escapeHtml(a.note||'')}</textarea></td>
<td style="padding:4px 8px"><button class="btn-del-row" onclick="deleteAffRow(${a.id})">Xóa</button></td>
</tr>`;
        });
        html+=`</tbody></table></td></tr>`;
      }
      html+=`<tr><td colspan="9" style="background:#fafbfc;padding:2px 0 8px 0"><button class="btn-add-acc" onclick="addAffAccount('${pe}','${de}')">+ Thêm account</button></td></tr>`;
    }
  });
  body.innerHTML=html;
}

function toggleDomain(partner,domain){const key=partner+'|'+domain;if(expandedDomains.has(key))expandedDomains.delete(key);else expandedDomains.add(key);filterData();}

async function addAffAccount(partner,domain){
  const{data,error}=await _sb.from('affiliate_accounts').insert({partner,domain,status:'Đã xin',dashboard_url:'',affiliate_link:'',account:'',landing_page:'',loai_tk_google:'',camp_status:'',note:''}).select().single();
  if(error){alert('Lỗi: '+error.message);return;}
  affiliateAccounts.push(data);
  filterData();
}

async function updateAffField(id,field,value){
  const{error}=await _sb.from('affiliate_accounts').update({[field]:value}).eq('id',id);
  if(error){alert('Lỗi lưu: '+error.message);return;}
  const idx=affiliateAccounts.findIndex(a=>a.id===id);
  if(idx>=0)affiliateAccounts[idx][field]=value;
  if(field==='camp_status')filterData();
}

async function deleteAffRow(id){
  if(!confirm('Xóa account này?'))return;
  const{error}=await _sb.from('affiliate_accounts').delete().eq('id',id);
  if(error){alert('Lỗi: '+error.message);return;}
  affiliateAccounts=affiliateAccounts.filter(a=>a.id!==id);
  filterData();
}

async function updateProjectField(partner,domain,field,value){
  const{error}=await _sb.from('projects').update({[field]:value}).eq('partner',partner).eq('domain',domain);
  if(error){alert('Lỗi lưu: '+error.message);return;}
  const idx=rawData.findIndex(r=>r.partner===partner&&r.domain===domain);
  if(idx>=0)rawData[idx][field]=value;
}

// ── Camp tab ──
function renderCamp(){
  renderHeader('camp');
  const body=document.getElementById('tableBody');
  let filtered=affiliateAccounts.filter(a=>a.camp_status);
  if(campFilter!=='all')filtered=filtered.filter(a=>a.camp_status===campFilter);
  if(!filtered.length){body.innerHTML='<tr><td colspan="9" class="no-results">Chưa có account nào lên camp.<br>Vào tab <strong>Affiliate</strong> → chọn Status Camp cho account.</td></tr>';return;}

  let html='';
  filtered.forEach((a,i)=>{
    const cls=a.camp_status==='Đang chạy'?'running':a.camp_status==='Tạm ngưng'?'changed':'removed';
    html+=`<tr>
<td style="text-align:center;color:#999;font-size:12px">${i+1}</td>
<td style="font-weight:600;color:#0f3460">${escapeHtml(a.domain)}</td>
<td style="font-size:12px;color:#555">${escapeHtml(a.account||'—')}</td>
<td style="font-size:12px">${escapeHtml(a.loai_tk_google||'—')}</td>
<td><span class="badge ${cls}">${escapeHtml(a.camp_status)}</span></td>
<td style="font-size:12px;word-break:break-all">${a.affiliate_link?`<a href="${escapeHtml(a.affiliate_link)}" target="_blank" style="color:#0f3460">${escapeHtml(a.affiliate_link)}</a>`:'—'}</td>
<td style="font-size:12px;word-break:break-all">${a.landing_page?`<a href="${escapeHtml(a.landing_page)}" target="_blank" style="color:#0f3460">${escapeHtml(a.landing_page)}</a>`:'—'}</td>
<td style="font-size:12px;color:#555">${escapeHtml(a.note||'—')}</td>
<td><textarea class="aff-sub-textarea" style="width:200px;min-height:52px" onblur="updateAffField(${a.id},'payment_info',this.value)" placeholder="Thông tin thanh toán...">${escapeHtml(a.payment_info||'')}</textarea></td>
</tr>`;
  });
  body.innerHTML=html;
}

// ── Main filter/render ──
function filterData(){
  if(currentView==='affiliate'){renderAffiliate();return;}
  if(currentView==='camp'){renderCamp();return;}
  const search=document.getElementById('search').value.toLowerCase(),pv=document.getElementById('partnerFilter').value;
  const df=document.getElementById('duyetFilter').value;
  renderHeader(currentView);
  const body=document.getElementById('tableBody');
  const colCount=hasComparison?(currentView==='detail'?16:10):(currentView==='detail'?15:9);
  if(currentView==='detail'){
    let f=rawData.filter(r=>{
      const ms=!search||r.partner.toLowerCase().includes(search)||r.domain.toLowerCase().includes(search)||(r.url_original||'').toLowerCase().includes(search);
      const mp=!pv||r.partner===pv;
      const mc=changeFilter==='all'||(changeFilter==='new'&&r.change==='new')||(changeFilter==='changed'&&r.change==='changed')||(changeFilter==='same'&&(!r.change||r.change==='same'));
      const md=!df||(df==='1'&&r.duyet)||(df==='0'&&!r.duyet);
      return ms&&mp&&mc&&md;
    });
    if(sortCol)f.sort((a,b)=>{let va=(a[sortCol]||'').toString().toLowerCase(),vb=(b[sortCol]||'').toString().toLowerCase();return va<vb?(sortAsc?-1:1):va>vb?(sortAsc?1:-1):0});
    let lp=null,html='',stt=0;
    f.forEach(r=>{
      stt++;
      if(r.partner!==lp){
        const c=rawData.filter(x=>x.partner===r.partner).length;
        const pe=r.partner.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
        html+=`<tr class="partner-group-row"><td colspan="${colCount}">${escapeHtml(r.partner)} <span class="count" style="cursor:pointer;text-decoration:underline" onclick="openPartnerDetail('${pe}')">${c} dự án →</span></td></tr>`;
        lp=r.partner;
      }
      const badge=r.status==='Đang chạy'?'<span class="badge running">Đang chạy</span>':'<span class="badge stopped">Ngưng chạy</span>';
      let rc='',cb='';
      if(hasComparison){if(r.change==='new'){rc='row-new';cb='<span class="badge new">Mới</span>'}else if(r.change==='changed'){rc='row-changed';cb=`<span class="badge changed">${escapeHtml(r.old_status||'')} → ${escapeHtml(r.status)}</span>`}else cb='<span style="color:#ccc;font-size:11px">—</span>'}
      const cTd=hasComparison?`<td>${cb}</td>`:'';
      const duyetBadge=r.duyet?'<span class="badge duyet">✓</span>':'<span style="color:#ddd">—</span>';
      const pe=r.partner.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      const de=r.domain.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      const ad=`<a href="${escapeHtml(r.ad_library_url||'#')}" target="_blank" class="ad-link" onclick="event.stopPropagation()"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>Google Ads</a>`;
      html+=`<tr class="${rc}" style="cursor:pointer" onclick="openEditModal('${pe}','${de}',event)">
<td style="text-align:center;color:#999;font-size:12px">${stt}</td>
<td class="partner-cell">${escapeHtml(r.partner)}</td>
<td class="domain-cell">${escapeHtml(r.domain)}</td>
<td><span class="url-cell-wrap"><a href="${escapeHtml(r.url_normalized||'')}" target="_blank" onclick="event.stopPropagation()">${escapeHtml(r.url_normalized||'')}</a><button class="copy-btn" onclick="copyUrl('${escapeHtml(r.url_normalized||'')}',this);event.stopPropagation()" title="Copy"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button></span></td>
<td class="url-orig-cell" title="${escapeHtml(r.url_original||'')}"><a href="${escapeHtml((r.url_original||'').startsWith('http')?r.url_original:'https://'+(r.url_original||''))}" target="_blank" onclick="event.stopPropagation()">${escapeHtml(truncateUrl(r.url_original||'',40))}</a></td>
<td>${badge}</td>
<td style="font-size:12px;color:#666;white-space:nowrap">${escapeHtml(r.last_date||'')}</td>
<td>${ad}</td>
<td style="text-align:center">${duyetBadge}</td>
<td onclick="event.stopPropagation()" style="min-width:120px"><input style="width:110px;padding:3px 6px;border:1px solid #e0e0e0;border-radius:4px;font-size:12px;color:#555;background:transparent;outline:none" value="${escapeHtml(r.traffic||'')}" placeholder="Traffic..." onfocus="this.style.borderColor='#0f3460';this.style.background='#fff'" onblur="this.style.borderColor='#e0e0e0';this.style.background='transparent';updateProjectField('${pe}','${de}','traffic',this.value)"></td>
<td style="font-size:12px;color:#555;min-width:150px">${escapeHtml(r.ghi_chu||'')}</td>
<td>${r.ads_policy==='Cho chạy Ads'?'<span class="badge running">Cho chạy Ads</span>':r.ads_policy==='Cấm Brand'?'<span class="badge changed">Cấm Brand</span>':r.ads_policy==='Cấm SEM'?'<span class="badge removed">Cấm SEM</span>':r.ads_policy==='Cấm hoàn toàn'?'<span class="badge removed" style="background:#6b0000;color:#fff">Cấm hoàn toàn</span>':'—'}</td>
<td onclick="event.stopPropagation()" style="min-width:160px">
  <select class="aff-sub-select" onchange="updateProjectField('${pe}','${de}','traffic_type',this.value);document.getElementById('dur_'+${r.id||0}).style.display=this.value==='Recurring'?'block':'none'">
    <option value=""${!r.traffic_type?' selected':''}>—</option>
    <option value="Recurring"${r.traffic_type==='Recurring'?' selected':''}>Recurring</option>
    <option value="One-time"${r.traffic_type==='One-time'?' selected':''}>One-time</option>
    <option value="Lifetime"${r.traffic_type==='Lifetime'?' selected':''}>Lifetime</option>
  </select>
  <input id="dur_${r.id||0}" style="display:${r.traffic_type==='Recurring'?'block':'none'};width:100px;margin-top:3px;padding:2px 6px;border:1px solid #e0e0e0;border-radius:4px;font-size:11px;outline:none" value="${escapeHtml(r.traffic_duration||'')}" placeholder="Thời hạn..." onblur="updateProjectField('${pe}','${de}','traffic_duration',this.value)">
</td>
<td onclick="event.stopPropagation()"><input style="width:110px;padding:3px 6px;border:1px solid #e0e0e0;border-radius:4px;font-size:12px;color:#555;background:transparent;outline:none" value="${escapeHtml(r.cookies||'')}" placeholder="Cookies..." onfocus="this.style.borderColor='#0f3460';this.style.background='#fff'" onblur="this.style.borderColor='#e0e0e0';this.style.background='transparent';updateProjectField('${pe}','${de}','cookies',this.value)"></td>
<td onclick="event.stopPropagation()"><input style="width:80px;padding:3px 6px;border:1px solid #e0e0e0;border-radius:4px;font-size:12px;color:#555;background:transparent;outline:none;text-align:center" value="${escapeHtml(r.hoa_hong||'')}" placeholder="%" onfocus="this.style.borderColor='#0f3460';this.style.background='#fff'" onblur="this.style.borderColor='#e0e0e0';this.style.background='transparent';updateProjectField('${pe}','${de}','hoa_hong',this.value)"></td>
${cTd}
</tr>`;
    });
    if(hasComparison&&(changeFilter==='all'||changeFilter==='new')){
      const rf=removedData.filter(r=>{const ms=!search||r.partner.toLowerCase().includes(search)||r.domain.toLowerCase().includes(search);const mp=!pv||r.partner===pv;return ms&&mp});
      if(rf.length){html+=`<tr class="partner-group-row" style="background:#fce4ec"><td colspan="${colCount}">Đã xóa (${rf.length}) <span class="count" style="background:#e94560">${rf.length} bỏ</span></td></tr>`;rf.forEach(r=>{html+=`<tr style="opacity:.6;text-decoration:line-through"><td></td><td class="partner-cell">${escapeHtml(r.partner)}</td><td class="domain-cell">${escapeHtml(r.domain)}</td><td><a href="${escapeHtml(r.url_normalized)}" target="_blank" style="text-decoration:line-through">${escapeHtml(r.url_normalized)}</a></td><td></td><td><span class="badge removed">Đã xóa</span></td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>${hasComparison?'<td><span class="badge removed">Xóa</span></td>':''}</tr>`})}}
    if(!html)html=`<tr><td colspan="${colCount}" class="no-results">Không tìm thấy kết quả</td></tr>`;
    body.innerHTML=html;
  }else{
    let f=summaryData.filter(r=>{const ms=!search||r.partner.toLowerCase().includes(search);const mp=!pv||r.partner===pv;return ms&&mp});
    if(sortCol)f.sort((a,b)=>{let va=a[sortCol],vb=b[sortCol];if(typeof va==='string'){va=va.toLowerCase();vb=(vb||'').toString().toLowerCase()}return va<vb?(sortAsc?-1:1):va>vb?(sortAsc?1:-1):0});else f.sort((a,b)=>b.total-a.total);
    let html='',stt2=0;
    f.forEach(r=>{
      stt2++;
      const recs=rawData.filter(x=>x.partner===r.partner);
      const stopped=recs.filter(x=>x.status!=='Đang chạy').length;
      const domains=new Set(recs.map(x=>x.domain)).size;
      const lastDate=recs.map(x=>x.last_date||'').filter(Boolean).sort().pop()||'';
      const adUrl=adsLinks[r.partner]||'';
      const cTd=hasComparison?`<td>${r.new_count?'<span class="badge new">+'+r.new_count+'</span>':'<span style="color:#ccc">—</span>'}</td>`:'';
      const adTd=adUrl?`<td><a href="${escapeHtml(adUrl)}" target="_blank" class="ad-link"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>Google Ads</a></td>`:'<td>—</td>';
      r.stopped=stopped;r.domains=domains;r.last_date=lastDate;
      const pe=r.partner.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      html+=`<tr><td style="text-align:center;color:#999;font-size:12px">${stt2}</td><td class="partner-cell">${escapeHtml(r.partner)}</td><td><strong>${r.total}</strong></td><td><span class="badge running">${r.running}</span></td><td>${stopped?'<span class="badge stopped">'+stopped+'</span>':'<span style="color:#ccc">—</span>'}</td><td style="color:#888">${domains}</td><td style="font-size:12px;color:#666;white-space:nowrap">${escapeHtml(lastDate)}</td>${adTd}${cTd}<td><button class="copy-btn" onclick="openPartnerDetail('${pe}')" title="Xem chi tiết" style="width:auto;padding:4px 10px;font-size:12px;font-weight:600">Chi tiết →</button></td></tr>`;
    });
    if(!html)html=`<tr><td colspan="${colCount}" class="no-results">Không tìm thấy kết quả</td></tr>`;
    body.innerHTML=html;
  }
}

function sortBy(col){if(sortCol===col)sortAsc=!sortAsc;else{sortCol=col;sortAsc=true}filterData()}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();closeEditModal();}if(e.key==='Enter'&&editingRow&&!e.shiftKey){e.preventDefault();saveEdit();}});
loadData();
</script>
</body>
</html>'''

    html = HTML
    html = html.replace("__TIMESTAMP__", timestamp)
    html = html.replace("__COMPARE_INFO__", compare_info)
    html = html.replace("__REMOVED__", ",".join(removed_js))
    html = html.replace("__HAS_COMP__", "true" if has_comparison else "false")
    html = html.replace("__HISTORY__", history_js)
    html = html.replace("__CHIP_NEW__", chip_new)
    html = html.replace("__CHIP_CHANGED__", chip_changed)
    html = html.replace("__SUPABASE_URL__", supabase_url)
    html = html.replace("__SUPABASE_ANON_KEY__", supabase_anon_key)
    return html

# ==================== MAIN ====================

def main():
    records, summary = parse_raw_data(RAW_FILE)

    snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json")])
    prev_snap = None
    prev_timestamp = ""
    if snapshots:
        with open(os.path.join(SNAPSHOT_DIR, snapshots[-1]), encoding="utf-8") as f:
            prev_data = json.load(f)
        prev_snap = prev_data.get("data", {})
        prev_timestamp = prev_data.get("timestamp", "")

    current_snap = build_snapshot(records)
    if snapshots and prev_snap == current_snap:
        has_comparison = False
        removed = []
        for r in records:
            r["change"] = "same"
    else:
        has_comparison, removed = detect_changes(records, prev_snap)

    now = datetime.now()
    timestamp = now.strftime("%d/%m/%Y %H:%M:%S")

    partner_history, last_update = build_partner_history(SNAPSHOT_DIR, records, timestamp)

    # Gắn last_date vào từng record trước khi upsert
    for r in records:
        key = f"{r['partner']}|{r['domain']}"
        r["last_date"] = last_update.get(key, timestamp)

    html = build_html(records, removed, has_comparison, timestamp, prev_timestamp, partner_history, SUPABASE_URL, SUPABASE_ANON_KEY)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    os.makedirs(os.path.dirname(DEPLOY_HTML), exist_ok=True)
    with open(DEPLOY_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # Upsert lên Supabase
    upsert_to_supabase(records, timestamp)

    snap_file = os.path.join(SNAPSHOT_DIR, f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.json")
    with open(snap_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": timestamp, "data": current_snap}, f, ensure_ascii=False, indent=2)

    new_count     = sum(1 for r in records if r.get("change") == "new")
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
    print(f"  Snapshot:       {snap_file}")
    print("=" * 50)

if __name__ == "__main__":
    main()
