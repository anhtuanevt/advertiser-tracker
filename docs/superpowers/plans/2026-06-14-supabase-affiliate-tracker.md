# Supabase + Affiliate Tracker Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate QC Tracker from hardcoded HTML data to Supabase, add 3 editable fields per project (Duyệt/Traffic/Ghi chú), and add 2 new tabs (Affiliate + Camp) for tracking affiliate registrations.

**Architecture:** Python `update.py` upserts parsed data to Supabase on each run; HTML becomes a shell that fetches from Supabase on load. `partnerHistory`, `removedData`, `hasComparison` remain embedded in HTML (Python-computed metadata). Browser calls Supabase REST API directly using anon key + RLS.

**Tech Stack:** Supabase (PostgreSQL + REST), Supabase JS SDK v2 (CDN), Python `supabase` library, static HTML on Vercel.

---

## SUPABASE SETUP (Manual — do once)

### 1. Create Supabase account + project
- Go to https://supabase.com → Sign up (free)
- Create new project → choose any name + region + password
- Wait ~1 minute for project to provision

### 2. Run this SQL in Supabase SQL Editor (Dashboard → SQL Editor → New query)

```sql
-- Main projects table
CREATE TABLE projects (
  id             SERIAL PRIMARY KEY,
  partner        TEXT NOT NULL,
  domain         TEXT NOT NULL,
  url_original   TEXT DEFAULT '',
  url_normalized TEXT DEFAULT '',
  status         TEXT DEFAULT '',
  ad_library_url TEXT DEFAULT '',
  change         TEXT DEFAULT 'same',
  old_status     TEXT DEFAULT '',
  last_date      TEXT DEFAULT '',
  duyet          BOOLEAN DEFAULT false,
  traffic        TEXT DEFAULT '',
  ghi_chu        TEXT DEFAULT '',
  UNIQUE(partner, domain)
);

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY "anon_all" ON projects FOR ALL TO anon USING (true) WITH CHECK (true);

-- Affiliate accounts table (multiple rows per project)
CREATE TABLE affiliate_accounts (
  id             SERIAL PRIMARY KEY,
  partner        TEXT NOT NULL,
  domain         TEXT NOT NULL,
  status         TEXT DEFAULT 'Đã xin',
  dashboard_url  TEXT DEFAULT '',
  affiliate_link TEXT DEFAULT '',
  account        TEXT DEFAULT '',
  landing_page   TEXT DEFAULT '',
  loai_tk_google TEXT DEFAULT '',
  camp_status    TEXT DEFAULT '',
  note           TEXT DEFAULT '',
  created_at     TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE affiliate_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "anon_all" ON affiliate_accounts FOR ALL TO anon USING (true) WITH CHECK (true);
```

### 3. Collect credentials
Go to Project Settings → API:
- `Project URL` → paste into `SUPABASE_URL` in update.py
- `anon` public key → paste into `SUPABASE_ANON_KEY` in update.py
- `service_role` secret key → paste into `SUPABASE_SERVICE_KEY` in update.py

---

## Task 1: Update update.py — Python Supabase upsert

**Files:** Modify `/Users/bruce/Desktop/data/update.py`

- [ ] Install supabase Python library: `pip install supabase`
- [ ] Add config block after existing CONFIG section
- [ ] Add `upsert_to_supabase()` function
- [ ] Update `build_html()` signature to accept supabase keys
- [ ] Call upsert + update build_html call in `main()`

---

## Task 2: Rewrite HTML template in update.py

**Files:** Modify `/Users/bruce/Desktop/data/update.py` (the `HTML = r'''...'''` template string)

### Changes to template:
- Add Supabase JS SDK CDN before `</head>`
- Add 2 new tabs: Affiliate, Camp
- Add camp filter chips div
- Add edit popup modal HTML
- In `<script>`:
  - Remove `const rawData=[__DATA__]` and `const summaryData=[__SUMMARY__]`
  - Add Supabase config placeholders + createClient
  - Add `loadData()`, `loadAffiliateAccounts()`, `computeSummary()`, `computeAdsLinks()`
  - Update `switchView()` for 4 tabs
  - Update `renderHeader()` for affiliate/camp
  - Update `filterData()` to dispatch to renderAffiliate/renderCamp
  - Add `renderAffiliate()`, `renderCamp()`
  - Add `openEditModal()`, `closeEditModal()`, `saveEdit()`
  - Add `toggleDomain()`, `addAffAccount()`, `updateAffField()`, `deleteAffRow()`
  - Add `setCampFilter()`
  - Replace final `filterData()` with `loadData()`
- Add new CSS for edit popup, affiliate table, camp chips

---

## Task 3: Run + verify + deploy

- [ ] `pip install supabase`
- [ ] Fill in Supabase credentials in update.py
- [ ] `python3 update.py` — verify upsert success
- [ ] Open `vercel-app/public/index.html` in browser — verify data loads
- [ ] Test edit popup: click row → modify fields → save → verify in Supabase
- [ ] Test Affiliate tab
- [ ] Test Camp tab + filter chips
- [ ] `cd vercel-app && vercel --prod`
