# QC Tracker

Theo dõi nhà QC & dự án — dashboard tĩnh, deploy lên Vercel.

## Workflow hằng tuần

```
1. Paste data mới vào raw_data.txt
2. Chạy:  python3 update.py
3. Deploy:  cd vercel-app && npx vercel --prod
```

Xong! Mọi người xem dashboard qua link Vercel.

## Cấu trúc

```
├── raw_data.txt          # ← Paste data mới vào đây
├── update.py             # Chạy để build HTML
├── index.html            # Output (mở xem local)
├── snapshots/            # Lịch sử snapshot (auto)
└── vercel-app/
    └── public/
        └── index.html    # Copy tự động — deploy cái này
```

## Tính năng

- Normalize URL (bỏ UTM, www, tracking)
- So sánh tự động với lần trước (MỚI / ĐỔI / XÓA)
- Link Facebook Ad Library cho từng nhà QC
- Timestamp cập nhật
- Tìm kiếm, lọc, sắp xếp
