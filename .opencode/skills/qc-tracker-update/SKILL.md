---
name: qc-tracker-update
description: Use when the user provides raw advertiser/project data (TSV format) and wants to update the QC Tracker dashboard. Handles normalize, build HTML, change detection, push GitHub, and deploy Vercel.
---

# QC Tracker — Update Workflow

## Trigger
User provides raw data (TSV from spreadsheet) or says "update", "deploy", "data mới", "refresh data".

## Project Structure
```
/Users/bruce/Desktop/data/
├── raw_data.txt              # Raw TSV data (paste new data here)
├── update.py                 # Build script (normalize + change detection + HTML)
├── index.html                # Output (local preview)
├── snapshots/                # Auto-saved JSON snapshots (gitignored)
├── vercel-app/
│   ├── public/index.html     # Deploy copy (auto-generated)
│   └── vercel.json
└── .opencode/skills/qc-tracker-update/SKILL.md
```

## Steps (do ALL automatically)

### 1. Replace raw_data.txt
- Overwrite `/Users/bruce/Desktop/data/raw_data.txt` with the new TSV data from user
- Keep the header row as-is
- Preserve tab separation

### 2. Run build script
```bash
cd /Users/bruce/Desktop/data && python3 update.py
```
This automatically:
- Normalizes URLs (strips UTM, www, tracking params)
- Extracts Google Ads Transparency links from last column
- Compares with previous snapshot → detects NEW / CHANGED / REMOVED
- Builds `index.html` + `vercel-app/public/index.html`
- Saves timestamped snapshot to `snapshots/`
- Prints summary (partner count, projects, changes)

### 3. Verify output
- Open `index.html` to preview:
```bash
open /Users/bruce/Desktop/data/index.html
```

### 4. Commit + push to GitHub
```bash
cd /Users/bruce/Desktop/data && git add -A && git commit -m "Update data YYYY-MM-DD" && git push origin main
```

### 5. Deploy to Vercel
```bash
cd /Users/bruce/Desktop/data/vercel-app && vercel --prod --yes
```

### 6. Report to user
- Show the Vercel URL
- Show change summary (new/changed/removed counts)

## Data Format Rules
- Tab-separated (TSV)
- Row 1 = header (skip)
- Col 0 = Partner name (Nhà QC)
- Remaining cols alternate: URL, Status, URL, Status...
- Last non-empty col may contain Google Ads Transparency link (`adstransparency.google.com/...`)
- Status: "Đang chạy" or "Ngưng chạy"

## Key Details
- Vercel project name: `vercel-app`
- GitHub repo: `anhtuanevt/advertiser-tracker`
- Vercel output dir: `public` (configured in vercel.json)
- No build step needed — static HTML
- Snapshots are gitignored (local only)
- History accumulates from snapshots over time
