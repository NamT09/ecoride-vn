# Deploy bằng điện thoại

1. Tạo tài khoản GitHub và Vercel.
2. Tạo một PostgreSQL database trên Supabase hoặc Neon.
3. Tạo GitHub repository mới.
4. Upload toàn bộ file trong project này lên repository.
5. Vào Vercel → Add New → Project → chọn repository.
6. Trong Environment Variables thêm `DATABASE_URL` và `CRON_SECRET`.
7. Deploy.
8. Mở URL Vercel trên điện thoại.
9. Vào Vercel Logs nếu cần kiểm tra cron/collector.

Sau khi deploy thành công, trang web có thể mở trực tiếp trên điện thoại và thêm vào màn hình chính.
