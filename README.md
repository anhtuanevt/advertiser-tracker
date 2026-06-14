# Advertiser Tracker

Dashboard theo dõi nhà quảng cáo & dự án — static site, deploy trên Vercel.

## Links

- **Dashboard**: https://vercel-app-one-lilac.vercel.app
- **GitHub**: https://github.com/anhtuanevt/advertiser-tracker

## Workflow hằng tuần

```
1. Paste data mới vào raw_data.txt
2. Chạy:  python3 update.py
3. Preview:  open index.html
4. Deploy:
   git add -A && git commit -m "Update data" && git push origin main
   cd vercel-app && vercel --prod --yes
```

## Cấu trúc

```
├── raw_data.txt              # Raw TSV data (paste ở đây)
├── update.py                 # Build script (normalize + compare + HTML)
├── index.html                # Output (xem local)
├── snapshots/                # JSON snapshots (auto, gitignored)
├── .opencode/
│   └── skills/
│       └── qc-tracker-update/
│           └── SKILL.md      # Skill cho opencode tự động update + deploy
└── vercel-app/
    ├── public/
    │   └── index.html        # Deploy copy (auto-generated)
    └── vercel.json
```

## Tính năng

### Dashboard
- **Tab Chi tiết**: bảng đầy đủ với STT, nhà QC, domain, URL chuẩn hóa, URL gốc, trạng thái, ngày cập nhật, Google Ads link
- **Tab Tổng hợp**: per-partner stats (tổng, đang chạy, ngưng, domain, cập nhật cuối)
- **Search + filter** theo tên, domain, URL
- **Sort** click header cột
- **Copy URL** — nút copy bên cạnh mỗi URL
- **Compact layout** — tối đa không gian bảng

### Change Detection
- Tự động so sánh với snapshot trước
- Highlight: **Mới** (xanh) / **Đổi status** (vàng) / **Đã xóa** (đỏ, gạch ngang)
- Filter chips: Tất cả / Mới / Đổi / Không đổi
- Timestamp "Cập nhật lúc" + "so với lần trước"

### Partner Detail Modal
- Click "X dự án →" → mở overlay chi tiết
- Stats: tổng dự án, đang chạy, ngưng, domain
- Link Google Ads Transparency
- Bảng dự án — click row → expand history từng dự án (timeline: thêm/xóa/đổi status + ngày)
- Tổng quan lịch sử thay đổi toàn nhà QC
- Đóng: ESC / click outside / nút ×

### Data Processing
- Normalize URL (bỏ UTM, `www`, tracking params, `gclid`)
- Extract Google Ads Transparency link từ cột cuối
- Fallback Facebook Ad Library nếu không có link Google
- Snapshot tự lưu → history tích lũy theo thời gian

## Data Format (raw_data.txt)

- **Tab-separated (TSV)**
- **Row 1**: Header (bỏ qua khi parse)
- **Col 0**: Tên nhà QC
- **Col 1+**: Cặp [URL, Status] xen kẽ
- **Col cuối** (optional): Link Google Ads Transparency

```
Nhà QC	URL1	Status1	URL2	Status2	...	Link Ads Transparency
NGUYEN THI BICH HA	https://www.purevpn.com/	Đang chạy	https://www.apollo.io/	Đang chạy	https://adstransparency.google.com/advertiser/AR123...
```

## Tech Stack

- **Python 3**: update.py (parse + normalize + compare + HTML generate)
- **Vanilla HTML/CSS/JS**: self-contained, no framework, no backend
- **Vercel**: static hosting (output dir: `public`)
- **Git/GitHub**: version control

## opencode Skill

Skill `qc-tracker-update` đã setup. Trong opencode, chỉ cần paste data mới → bot tự:
1. Ghi raw_data.txt
2. Chạy update.py
3. Commit + push GitHub
4. Deploy Vercel
5. Trả link + summary
