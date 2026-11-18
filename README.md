# Vietnam Fuel Calculator — Vercel

Ứng dụng web tính tiền xăng theo số lít, chạy cloud trên Vercel và tự đồng bộ giá tham chiếu từ Bộ Công Thương.

## Cấu trúc project

```text
vietnam-fuel-calculator/
├── api/
│   └── index.py
├── index.html
├── app.js
├── style.css
├── manifest.webmanifest
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── vercel.json
```

Frontend được đặt ở repo root để Vercel phục vụ `index.html` trực tiếp. FastAPI nằm trong `api/index.py` và được Vercel nhận diện là Python Serverless Function. Không cần route rewrite cho frontend.

## Kiến trúc

- Frontend: HTML/CSS/JavaScript responsive, có PWA manifest.
- Backend: FastAPI trên Vercel Serverless Functions.
- Database: PostgreSQL (Supabase/Neon đều được).
- Price source: website Bộ Công Thương.
- Scheduler: Vercel Cron.
- Fallback: nếu nguồn giá lỗi, dữ liệu cuối cùng đã lưu không bị xóa.

Bộ Công Thương công bố các mức giá/giá cơ sở theo từng kỳ. App coi thời điểm công bố/áp dụng trong thông báo là dữ liệu nguồn, không giả định rằng mọi thay đổi đều xảy ra theo một lịch cố định.

## 1. PostgreSQL

Tạo một PostgreSQL database trên Supabase hoặc Neon và lấy connection string.

Environment variable cần có:

```env
DATABASE_URL=...
```

Khi API chạy lần đầu, bảng `fuel_prices` được tạo tự động nếu database account có quyền tạo bảng.

## 2. GitHub

Upload **nội dung bên trong project** lên repository, không upload một thư mục ZIP lồng bên trong. Repo phải có `index.html` ở root và `api/index.py` trong thư mục `api/`.

Không commit `.env`, secret, `__pycache__` hoặc `*.pyc`.

## 3. Vercel

Import repository vào Vercel. Không cần cấu hình Root Directory khác mặc định.

Environment Variables:

- `DATABASE_URL` = connection string PostgreSQL
- `CRON_SECRET` = chuỗi bí mật ngẫu nhiên

## 4. Deploy

Vercel sẽ phục vụ `index.html` ở `/` và các asset `app.js`, `style.css`, `manifest.webmanifest` ở root. FastAPI được phục vụ dưới `/api/*`.

Các endpoint chính:

- `GET /api/health`
- `GET /api/prices`
- `GET /api/prices/{code}`
- `GET /api/history`
- `GET /api/cron/update-prices` (Vercel Cron)
- `POST /api/cron/update-prices` (manual test)

## 5. Khởi tạo giá

Sau deploy, mở:

```text
https://<project>.vercel.app/api/prices?refresh=true
```

API sẽ tạo bảng nếu cần và thử lấy giá từ nguồn. Nếu lấy thành công, dữ liệu được lưu vào PostgreSQL.

Nếu lần refresh mới thất bại nhưng database đã có giá hợp lệ, API giữ và trả về giá đã lưu.

## 6. Cron

Project có hai lịch UTC:

- `08:10 UTC` = `15:10` giờ Việt Nam
- `09:30 UTC` = `16:30` giờ Việt Nam

Vercel Cron gọi endpoint bằng HTTP GET; project đã hỗ trợ GET cho endpoint này. POST vẫn được giữ để kiểm tra thủ công.

Khả năng chạy Cron với tần suất nào phụ thuộc gói Vercel hiện tại. Không nên thiết kế hệ thống phụ thuộc tuyệt đối vào Cron vì app còn có cơ chế refresh khi dữ liệu stale.

## 7. Bảo mật Cron

Backend yêu cầu `CRON_SECRET`. Request có thể cung cấp:

```text
Authorization: Bearer <CRON_SECRET>
```

hoặc:

```text
x-cron-secret: <CRON_SECRET>
```

Không commit secret thật lên GitHub.

## 8. Giá hiển thị

App hiển thị giá tham chiếu lấy từ thông báo của Bộ Công Thương, không khẳng định đây là giá bán thực tế tại từng cửa hàng.

## 9. Local development

Production không phụ thuộc PC/laptop đang bật. Sau khi deploy, frontend, API và Cron chạy trên hạ tầng Vercel; PostgreSQL nằm ở provider bên ngoài.
