---
name: qc-tracker-update
description: Use when the user provides raw advertiser/project data (TSV) or says "update", "deploy", "data mới", "refresh". Handles normalize, build HTML, change detection, history, push GitHub, deploy Vercel. Also use when user wants to add new data tabs/types to the dashboard.
---

# QC Tracker — Full Project Skill

## Project Overview
Dashboard tĩnh theo dõi nhà quảng cáo (QC) & dự án. Data update thủ công (paste TSV), build ra HTML tĩnh, deploy lên Vercel.

- **GitHub**: https://github.com/anhtuanevt/advertiser-tracker
- **Vercel**: https://vercel-app-one-lilac.vercel.app
- **Local dir**: `/Users/bruce/Desktop/data`

## File Structure
```
/Users/bruce/Desktop/data/
├── raw_data.txt                  # Raw TSV — paste data mới vào đây
├── update.py                     # Build script duy nhất (normalize + compare + HTML)
├── index.html                    # Output local preview
├── snapshots/                    # JSON snapshots (gitignored, local only)
│   └── snapshot_YYYYMMDD_HHMMSS.json
├── .opencode/
│   └── skills/
│       └── qc-tracker-update/
│           └── SKILL.md          # File này
├── vercel-app/
│   ├── public/
│   │   └── index.html            # Deploy copy (auto-generated bởi update.py)
│   ├── vercel.json               # { "outputDirectory": "public" }
│   └── README.md
└── README.md
```

## Data Format (raw_data.txt)

### Structure
- **Tab-separated (TSV)**
- **Row 1**: Header — skip khi parse
- **Col 0**: Tên nhà QC (partner name)
- **Col 1+**: Cặp [URL, Status] xen kẽ: URL1, Status1, URL2, Status2, ...
- **Last non-empty col**: Có thể chứa link Google Ads Transparency (`adstransparency.google.com/...`)

### Status values
- `Đang chạy` → running
- `Ngưng chạy` / `stop` / `paused` → stopped
- Empty → mặc định `Đang chạy`

### URL normalization
- Tự động bỏ: `www.`, UTM params, tracking params (`gclid`, `ps_*`, `gsxid`, etc.)
- Example: `https://www.purevpn.com/?utm_source=x` → `purevpn.com`

### Example row
```
NGUYEN THI BICH HA	https://www.purevpn.com/	Đang chạy	https://www.apollo.io/	Đang chạy	...	https://adstransparency.google.com/advertiser/AR06246427743257362433
```

## update.py — Build Script

### What it does (in order)
1. **Parse** raw_data.txt → records [{partner, url_original, domain, url_normalized, status, ad_library_url}]
2. **Extract** Google Ads Transparency link từ cột cuối (nếu có), fallback Facebook Ad Library
3. **Load** snapshot gần nhất từ `snapshots/`
4. **Compare** current vs previous → tag mỗi record: `new` / `changed` / `same` + detect `removed`
5. **Build history** từ tất cả snapshots → timeline per-partner + per-project
6. **Build last_update date** per project (ngày thay đổi gần nhất)
7. **Generate** `index.html` + `vercel-app/public/index.html` (self-contained, data embedded in JS)
8. **Save** snapshot mới `snapshots/snapshot_YYYYMMDD_HHMMSS.json`

### Output HTML features
- **Tab 1: Chi tiết dự án** — bảng đầy đủ: STT, Nhà QC, Domain, URL chuẩn hóa (+copy), URL gốc, Trạng thái, Ngày cập nhật, Google Ads link, Thay đổi
- **Tab 2: Tổng hợp** — per-partner: Tổng, Đang chạy, Ngưng, Domain, Cập nhật cuối, Google Ads, Chi tiết button
- **Modal chi tiết** — click "X dự án →" → overlay với: stats, link Ads, bảng dự án (click row → expand history), tổng quan timeline
- **Change filters** — chips: Tất cả / Mới / Đổi status / Không đổi
- **Search + filter** — theo tên, domain, URL
- **Sortable columns** — click header
- **Copy button** — bên cạnh mỗi URL
- **ESC / click outside** — đóng modal

## Workflow: Cập nhật data mới

### Khi user paste data mới:

**Step 1**: Overwrite `raw_data.txt`
```
→ Write tool: /Users/bruce/Desktop/data/raw_data.txt
```

**Step 2**: Run build
```bash
cd /Users/bruce/Desktop/data && python3 update.py
```
→ Kiểm tra output: số nhà QC, dự án, changes (new/changed/removed)

**Step 3**: Preview
```bash
open /Users/bruce/Desktop/data/index.html
```

**Step 4**: Commit + push
```bash
cd /Users/bruce/Desktop/data && git add -A && git commit -m "Update data $(date +%Y-%m-%d)" && git push origin main
```

**Step 5**: Deploy
```bash
cd /Users/bruce/Desktop/data/vercel-app && vercel --prod --yes
```

**Step 6**: Report to user
- Vercel URL
- Change summary

## Workflow: Deploy only (không có data mới)

```bash
cd /Users/bruce/Desktop/data && git add -A && git commit -m "Deploy $(date +%Y-%m-%d)" && git push origin main
cd vercel-app && vercel --prod --yes
```

## Mở rộng: Thêm tab data loại mới

Khi user muốn thêm một loại data mới (ví dụ: "Tab Campaign", "Tab Spend", "Tab Keywords"):

### Approach 1: Thêm tab mới vào HTML hiện tại
1. Thêm tab button trong HTML template (update.py)
2. Thêm data source file (vd: `raw_campaigns.txt`)
3. Thêm parse function trong update.py
4. Thêm render function trong JavaScript
5. Build + deploy

### Approach 2: Tạo page riêng
1. Tạo `update_campaigns.py` riêng
2. Output `vercel-app/public/campaigns.html`
3. Thêm nav link trên header

### Key principles khi mở rộng
- Giữ `update.py` làm script chính
- Mỗi data type có raw file riêng: `raw_<type>.txt`
- Snapshot dir dùng chung: `snapshots/`
- HTML output luôn copy cả `index.html` + `vercel-app/public/index.html`
- Tab mới phải có: search, filter, sort, copy, modal detail (nếu applicable)
- Giữ style CSS nhất quán (colors, badges, cards)

## Key Config
- **Vercel project**: `vercel-app` (account: anh-tuans-projects-f4dbcce4)
- **GitHub**: `anhtuanevt/advertiser-tracker` (branch: main)
- **Vercel output dir**: `public`
- **No build step** — static HTML only
- **Snapshots**: gitignored, local only, accumulate over time
- **History depth**: depends on how many times `update.py` has been run

## Notes
- `update.py` chứa toàn bộ logic: parse, normalize, compare, history, HTML template — all in one file
- HTML output là self-contained (CSS + JS embedded, data in JS arrays)
- Không cần backend, không cần database — chỉ Upstash Redis nếu muốn auto-fetch (đã bỏ)
- `vercel.json` chỉ có `{ "outputDirectory": "public" }`
