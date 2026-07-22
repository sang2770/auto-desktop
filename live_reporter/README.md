# TikTok LIVE Reporter

Script này chạy nền trên Windows, quét cửa sổ **TikTok LIVE Studio**, nhận diện màn hình kết thúc phiên, OCR ô **Tạm tính phiên LIVE này**, rồi gửi Telegram. Mỗi ảnh kết quả chỉ được ghi nhận một lần; dữ liệu được cộng dồn và gửi thêm một bản tổng kết cuối ngày.

5 ảnh trong thư mục `report` đã được dùng để thiết kế nhận diện cho cả hai bố cục TikTok hiện có. Các số tiền kỳ vọng là `$0.21`, `$0.11`, `$0.00`, `$0.54` và `$0.75`.

## Điều kiện hoạt động

- Windows 10/11 và đã đăng nhập vào tài khoản Windows.
- TikTok LIVE Studio đang mở, không bị thu nhỏ và vùng kết quả nhìn thấy trên màn hình.
- Python `.venv` của dự án và các gói trong `runner/requirements.txt`.
- Tesseract OCR cho Windows, có language data `eng`. Có thể thêm `vie` rồi đổi `ocr_languages` thành `eng+vie` để đọc tiếng Việt tốt hơn.
- Telegram bot token và chat ID. Phải mở bot và gửi `/start` ít nhất một lần trước khi test.

OCR màn hình không thể chạy ở màn hình khóa hoặc trước khi người dùng đăng nhập. Vì vậy Task Scheduler được cấu hình chạy ngay khi đăng nhập Windows, sau đó luôn chờ TikTok LIVE Studio xuất hiện.

## Cài tự khởi động

Mở PowerShell tại thư mục gốc dự án và chạy:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\live_reporter\install-autostart.ps1
```

Script cài đặt sẽ:

1. kiểm tra/cài dependency Python;
2. hỏi Telegram Bot Token và Chat ID;
3. gửi một tin Telegram thử;
4. tạo và khởi động task `AutoDesktop-TikTokLiveReporter`.

Token được lưu ngoài Git tại:

```text
%LOCALAPPDATA%\AutoDesktopLiveReporter\config.json
```

Muốn gửi kèm ảnh chụp kết quả hoặc thay đổi thời gian delay sau khi quét thành công (mặc định 120s = 2 phút):

```powershell
.\live_reporter\install-autostart.ps1 -SendScreenshot -PostSuccessDelaySeconds 120
```

## Chạy và kiểm tra thủ công

OCR 5 ảnh mẫu, không gửi Telegram:

```powershell
.\.venv\Scripts\python.exe .\live_reporter\live_reporter.py `
  --config "$env:LOCALAPPDATA\AutoDesktopLiveReporter\config.json" `
  --image-dir .\report
```

Quét màn hình một lần:

```powershell
.\.venv\Scripts\python.exe .\live_reporter\live_reporter.py `
  --config "$env:LOCALAPPDATA\AutoDesktopLiveReporter\config.json" `
  --once --verbose
```

Kiểm tra trạng thái và xem log:

```powershell
Get-ScheduledTask -TaskName AutoDesktop-TikTokLiveReporter
Get-Content "$env:LOCALAPPDATA\AutoDesktopLiveReporter\live-reporter.log" -Tail 100
```

Nếu TikTok đổi giao diện và OCR không nhận, bật `debug_screenshots` trong config, chạy lại một phiên, rồi xem ảnh ở `%LOCALAPPDATA%\AutoDesktopLiveReporter\debug`.

## Gỡ tự khởi động

Giữ lại config và lịch sử:

```powershell
.\live_reporter\uninstall-autostart.ps1
```

Xóa cả task, token, lịch sử và log:

```powershell
.\live_reporter\uninstall-autostart.ps1 -PurgeData
```

## Bảo mật

- Không đưa bot token vào Git hoặc gửi token cho người khác.
- Nếu token từng bị lộ, dùng BotFather để thu hồi và tạo token mới.
- `send_screenshot` mặc định tắt vì ảnh LIVE có thể chứa chat/thông tin riêng tư.
