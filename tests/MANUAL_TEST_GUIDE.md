# 📋 Hướng dẫn Test thủ công — Duty Logger Bot

> Dùng tài liệu này để test bot trực tiếp trên Discord sau khi chạy `.\scripts\run_local.ps1`

---

## ⚙️ Chuẩn bị trước khi test

### 1. Khởi động bot
```powershell
.\scripts\run_local.ps1
```
Bot online → trạng thái xanh ✅ trong Discord.

### 2. Setup guild (chạy 1 lần)
Dùng tài khoản **Owner** hoặc **Admin**:
```
/setup role admin    @<role-admin>
/setup role mod      @<role-mod>
/setup role member   @<role-member>
/setup channel log   #<channel-log>
```

### 3. Tài khoản cần có
| Tài khoản | Role | Dùng cho |
|-----------|------|----------|
| Tài khoản A | DUTY_MEMBER | Test upload log của chính mình |
| Tài khoản B | DUTY_MOD | Test bypass tên, xem log người khác |
| Tài khoản C | DUTY_ADMIN | Test xóa log |
| Tài khoản D | Không có role | Test bị chặn |

### 4. Nội dung LOG DUTY mẫu
Copy và lưu sẵn các log này để dùng trong test:

```
LOG DUTY
Tên: <Discord display name của bạn>
Thời gian làm việc: 120 phút
Thời gian bắt đầu: 01/05/2026 08:00:00
Thời gian kết thúc: 01/05/2026 10:00:00
made by • DutyBot Friday May 01 08:00:00 2026
```

---

## 🧪 Danh sách Test Cases

---

### 📌 NHÓM 1 — Auto-scan (Gửi LOG DUTY vào channel)

> Bot tự động quét và lưu khi tin nhắn khớp định dạng LOG DUTY trong log_channel

---

**TC-01 — Gửi log hợp lệ của chính mình**
- **Chuẩn bị**: Tài khoản A (MEMBER), đứng trong `#log-channel`
- **Bước**: Paste nội dung LOG DUTY (tên khớp display name tài khoản A)
- **Kỳ vọng**: Bot react ✅ vào tin nhắn, KHÔNG reply lỗi
- **Kiểm tra DB**: `/log view` → thấy ca vừa lưu

---

**TC-02 — Gửi lại log đã tồn tại (duplicate)**
- **Chuẩn bị**: Đã thực hiện TC-01
- **Bước**: Paste lại **đúng nội dung** log đó
- **Kỳ vọng**: Bot react 🔁 (im lặng, không reply lỗi)
- **Lý do**: Duplicate bị bỏ qua âm thầm để tránh spam

---

**TC-03 — Gửi log tên người khác (tự gửi hộ người khác)**
- **Chuẩn bị**: Tài khoản A, paste log có tên của tài khoản B
- **Kỳ vọng**: Bot react 🚫 + reply embed lỗi "Tên không khớp"
- **Lý do**: Auto-scan không cho phép gửi log hộ người khác, kể cả MOD

---

**TC-04 — Gửi log ở channel SAI**
- **Bước**: Tài khoản A gửi LOG DUTY trong channel bất kỳ (không phải log_channel)
- **Kỳ vọng**: Bot không phản ứng gì (ignore hoàn toàn)

---

**TC-05 — Gửi log không phải định dạng**
- **Bước**: Gửi "Hello world" hoặc tin nhắn thông thường vào log_channel
- **Kỳ vọng**: Bot không phản ứng gì

---

**TC-06 — Gửi log ngày trong quá khứ**
- **Bước**: Paste log với ngày **15/04/2026** (tuần trước)
- **Kỳ vọng**: Bot react ✅ — log quá khứ được chấp nhận
- **Kiểm tra**: `/log view` → thấy ca ngày 15/04

---

**TC-07 — Gửi log ca trùng giờ (overlap)**
- **Chuẩn bị**: Đã có log 08:00-10:00 ngày 01/05
- **Bước**: Paste log **09:00-11:00** ngày 01/05 (trùng 1 tiếng)
- **Kỳ vọng**: Bot react 🚫 + reply embed lỗi "Chồng lấp" kèm thông tin ca cũ

---

**TC-08 — Gửi log ca liên tiếp (không overlap)**
- **Chuẩn bị**: Đã có log 08:00-10:00 ngày 01/05
- **Bước**: Paste log **10:00-12:00** ngày 01/05 (bắt đầu đúng lúc ca cũ kết thúc)
- **Kỳ vọng**: Bot react ✅ — ca liên tiếp được phép

---

**TC-09 — Gửi log tương lai (chưa diễn ra)**
- **Bước**: Paste log với ngày **mai** (thời gian bắt đầu trong tương lai)
- **Kỳ vọng**: Bot react 🚫 + reply embed lỗi "Không thể log ca trực chưa bắt đầu"

---

**TC-10 — Gửi log duration không khớp (sai > 5 phút)**
- **Bước**: Paste log: bắt đầu 08:00, kết thúc 10:00 nhưng ghi **30 phút**
- **Kỳ vọng**: Bot react ⚠️ + reply lỗi "Thời gian không khớp"

---

### 📌 NHÓM 2 — /log forward (Paste text thủ công)

---

**TC-11 — Forward log hợp lệ của chính mình**
- **Bước**: `/log forward text:<nội dung LOG DUTY hợp lệ>`
- **Kỳ vọng**: Bot gửi embed xác nhận kèm nút **✅ Xác nhận lưu** / **❌ Huỷ**

---

**TC-12 — Bấm Xác nhận**
- **Tiếp theo TC-11**: Bấm nút ✅ Xác nhận lưu
- **Kỳ vọng**: Embed đổi thành thông báo thành công, nút bị disable
- **Kiểm tra**: `/log view` → thấy ca vừa lưu

---

**TC-13 — Bấm Huỷ**
- **Tiếp theo TC-11** (lần khác): Bấm nút ❌ Huỷ
- **Kỳ vọng**: Bot trả về "Đã huỷ lưu log", nút bị disable
- **Kiểm tra**: `/log view` → KHÔNG thấy ca đó

---

**TC-14 — Timeout (không bấm gì trong 60 giây)**
- **Tiếp theo TC-11** (lần khác): Chờ 60 giây không làm gì
- **Kỳ vọng**: Bot tự edit message → "⏰ Hết thời gian xác nhận", nút bị disable

---

**TC-15 — Forward text không hợp lệ**
- **Bước**: `/log forward text:Hello world không phải log`
- **Kỳ vọng**: Bot trả lỗi "Không nhận diện được định dạng LOG DUTY"

---

**TC-16 — Forward log của người khác (tài khoản MEMBER)**
- **Bước**: Tài khoản A (MEMBER) dùng `/log forward` với tên của tài khoản B
- **Kỳ vọng**: Bot trả lỗi "Tên không khớp... Mod+ mới có thể paste hộ người khác"

---

**TC-17 — MOD forward log hộ người khác**
- **Bước**: Tài khoản B (MOD) dùng `/log forward` với LOG DUTY tên của tài khoản A
- **Kỳ vọng**: Bot gửi embed xác nhận bình thường
- Sau khi confirm: `/log view thanh_vien:@A` → thấy log được ghi cho tài khoản A

---

**TC-18 — MOD forward với tên không tồn tại trong server**
- **Bước**: Tài khoản B (MOD) forward log có tên "Nguyễn Người Lạ" (không có trong server)
- **Kỳ vọng**: Bot trả lỗi "Không tìm thấy thành viên... trong server"

---

### 📌 NHÓM 3 — /log upload (OCR ảnh)

---

**TC-19 — Upload ảnh LOG DUTY hợp lệ**
- **Bước**: `/log upload anh:<screenshot LOG DUTY rõ nét>`
- **Kỳ vọng**: Bot OCR xong → gửi embed xác nhận kèm thông tin parse được

---

**TC-20 — Upload ảnh không phải LOG DUTY**
- **Bước**: `/log upload anh:<ảnh meme, avatar, không liên quan>`
- **Kỳ vọng**: Bot trả lỗi "Không tìm thấy định dạng LOG DUTY trong ảnh"

---

**TC-21 — Upload file sai định dạng**
- **Bước**: Thử upload file `.pdf` hoặc `.gif`
- **Kỳ vọng**: Bot trả lỗi "Chỉ chấp nhận ảnh JPG, PNG hoặc WEBP"

---

**TC-22 — Upload ảnh quá lớn (>5MB)**
- **Bước**: Upload ảnh >5MB
- **Kỳ vọng**: Bot trả lỗi "Ảnh quá lớn. Tối đa 5MB"

---

**TC-23 — MOD upload hộ với tham số `ten`**
- **Bước**: Tài khoản B (MOD): `/log upload anh:<ảnh> ten:<tên tài khoản A>`
- **Kỳ vọng**: Bot xác nhận, sau confirm log được ghi cho tài khoản A

---

### 📌 NHÓM 4 — /log view (Xem lịch sử)

---

**TC-24 — Xem log của chính mình (MEMBER)**
- **Bước**: Tài khoản A: `/log view`
- **Kỳ vọng**: Embed liệt kê các ca trực của tài khoản A, có tổng giờ

---

**TC-25 — Xem log của người khác (MEMBER)**
- **Bước**: Tài khoản A: `/log view thanh_vien:@B`
- **Kỳ vọng**: Bot trả lỗi "Bạn cần role DUTY_MOD hoặc cao hơn"

---

**TC-26 — Xem tất cả log (MOD)**
- **Bước**: Tài khoản B (MOD): `/log view tat_ca:True`
- **Kỳ vọng**: Embed bảng tất cả ca trực của mọi người, sắp xếp theo user + thời gian

---

**TC-27 — Xem log người khác (MOD)**
- **Bước**: Tài khoản B (MOD): `/log view thanh_vien:@A`
- **Kỳ vọng**: Embed hiển thị đúng log của tài khoản A

---

**TC-28 — Phân trang**
- **Chuẩn bị**: Có > 30 ca trực
- **Bước**: `/log view trang:2`
- **Kỳ vọng**: Hiển thị đúng trang 2, có thông tin "Trang 2/X"

---

**TC-29 — Filter theo tên**
- **Bước**: Tài khoản B (MOD): `/log view ten:Nguyễn`
- **Kỳ vọng**: Chỉ hiện các log có username chứa "Nguyễn"

---

### 📌 NHÓM 5 — /log delete (Xóa log)

---

**TC-30 — Xóa log (ADMIN)**
- **Chuẩn bị**: Biết ID của 1 ca trực (xem qua `/log view`)
- **Bước**: Tài khoản C (ADMIN): `/log delete id:<id>`
- **Kỳ vọng**: Bot xác nhận "Đã xóa log #X", ca không còn trong `/log view`

---

**TC-31 — Xóa log của guild khác (ADMIN)**
- **Bước**: `/log delete id:<id thuộc guild khác>`
- **Kỳ vọng**: Bot trả lỗi "Không tìm thấy log với ID X trong server này"

---

**TC-32 — Xóa log (MEMBER/MOD)**
- **Bước**: Tài khoản A hoặc B dùng `/log delete id:<id>`
- **Kỳ vọng**: Bot trả lỗi "Bạn cần role DUTY_ADMIN"

---

### 📌 NHÓM 6 — Phân quyền & Rate limit

---

**TC-33 — Tài khoản không có role**
- **Bước**: Tài khoản D (không role) dùng `/log forward`
- **Kỳ vọng**: Bot trả lỗi "Bạn cần role DUTY_MEMBER hoặc cao hơn"

---

**TC-34 — Rate limit upload (5 lần/60 giây)**
- **Bước**: Tài khoản A dùng `/log upload` hoặc `/log forward` hơn 5 lần trong 60 giây
- **Kỳ vọng**: Lần thứ 6 → Bot trả "Bạn dùng lệnh quá nhanh! Thử lại sau Xs"

---

**TC-35 — Guild owner có quyền ADMIN**
- **Bước**: Owner server dùng `/log delete` dù không có role DUTY_ADMIN
- **Kỳ vọng**: Lệnh chạy thành công (guild owner bypass role check)

---

### 📌 NHÓM 7 — /top và /stats

---

**TC-36 — Xem top trực tháng này**
- **Bước**: `/top period:month`
- **Kỳ vọng**: Embed bảng xếp hạng 🥇🥈🥉 với tổng giờ và số ca

---

**TC-37 — Xem top tuần này**
- **Bước**: `/top period:week`
- **Kỳ vọng**: Bảng xếp hạng chỉ tính ca trong tuần hiện tại (Thứ 2 → CN)

---

**TC-38 — Xem bottom trực**
- **Bước**: `/bottom period:month`
- **Kỳ vọng**: Hiển thị người trực ít nhất, từ thấp lên cao

---

**TC-39 — Stats cá nhân**
- **Bước**: `/stats`
- **Kỳ vọng**: Embed thống kê của chính mình: tổng giờ, số ca, ca dài nhất/ngắn nhất

---

### 📌 NHÓM 8 — /export

---

**TC-40 — Xuất CSV (MOD)**
- **Bước**: Tài khoản B (MOD): `/export format:csv period:month`
- **Kỳ vọng**: Bot gửi link download file CSV (có hiệu lực 10 phút)

---

**TC-41 — Xuất Excel (MOD)**
- **Bước**: `/export format:excel period:month`
- **Kỳ vọng**: File .xlsx với cột: guild, user, started_at, ended_at, duration, week, month, quarter

---

**TC-42 — Export (MEMBER)**
- **Bước**: Tài khoản A (MEMBER) dùng `/export`
- **Kỳ vọng**: Bot trả lỗi "Bạn cần role DUTY_MOD hoặc cao hơn"

---

## 🔢 Bảng tổng hợp kết quả

Điền `✅ Pass` / `❌ Fail` / `⏭️ Skip` vào cột **Kết quả**:

| ID | Tên test | Kết quả | Ghi chú |
|----|----------|---------|---------|
| TC-01 | Auto-scan log hợp lệ | | |
| TC-02 | Duplicate bị bỏ qua (🔁) | | |
| TC-03 | Gửi log hộ người khác bị chặn | | |
| TC-04 | Sai channel bị ignore | | |
| TC-05 | Tin nhắn không phải log bị ignore | | |
| TC-06 | Log ngày quá khứ được chấp nhận | | |
| TC-07 | Overlap bị chặn (🚫) | | |
| TC-08 | Ca liên tiếp được chấp nhận | | |
| TC-09 | Log tương lai bị chặn | | |
| TC-10 | Duration không khớp bị chặn | | |
| TC-11 | /log forward embed xác nhận | | |
| TC-12 | Bấm Xác nhận lưu thành công | | |
| TC-13 | Bấm Huỷ không lưu | | |
| TC-14 | Timeout 60s nút disable | | |
| TC-15 | Forward text rác | | |
| TC-16 | MEMBER forward tên người khác bị chặn | | |
| TC-17 | MOD forward hộ người khác | | |
| TC-18 | MOD forward tên không tồn tại | | |
| TC-19 | Upload ảnh hợp lệ | | |
| TC-20 | Upload ảnh không phải LOG DUTY | | |
| TC-21 | Upload sai định dạng file | | |
| TC-22 | Upload ảnh quá 5MB | | |
| TC-23 | MOD upload hộ với tham số ten | | |
| TC-24 | /log view xem của mình | | |
| TC-25 | MEMBER xem log người khác bị chặn | | |
| TC-26 | MOD xem tất cả | | |
| TC-27 | MOD xem log người khác | | |
| TC-28 | Phân trang | | |
| TC-29 | Filter theo tên | | |
| TC-30 | ADMIN xóa log | | |
| TC-31 | Xóa log ID không thuộc guild | | |
| TC-32 | MEMBER/MOD xóa log bị chặn | | |
| TC-33 | Tài khoản không role bị chặn | | |
| TC-34 | Rate limit 5 lần/60s | | |
| TC-35 | Guild owner bypass role check | | |
| TC-36 | /top tháng này | | |
| TC-37 | /top tuần này | | |
| TC-38 | /bottom | | |
| TC-39 | /stats cá nhân | | |
| TC-40 | /export CSV | | |
| TC-41 | /export Excel | | |
| TC-42 | MEMBER export bị chặn | | |

---

## ⚡ Test nhanh (smoke test — 10 phút)

Nếu không có thời gian test đủ, chạy **tối thiểu** 7 cases này:

```
TC-01 → gửi log hợp lệ
TC-02 → gửi lại → react 🔁
TC-07 → gửi overlap → react 🚫
TC-09 → gửi tương lai → bị chặn
TC-06 → gửi ngày quá khứ → được nhận
TC-12 → /log forward → confirm
TC-30 → /log delete
```

---

## 🐛 Khi gặp bug

Ghi lại:
1. **TC-XX** gặp vấn đề
2. Nội dung LOG DUTY đã dùng (copy paste)
3. Kết quả thực tế (chụp màn hình embed)
4. Kết quả kỳ vọng
5. Kiểm tra log bot trong terminal để xem có lỗi không
