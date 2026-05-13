# Google Drive Server-Side Copy (Python)

Công cụ hỗ trợ sao chép dữ liệu (file và thư mục) trực tiếp giữa các tài khoản Google Drive mà **không cần tải về máy tính**. Quá trình sao chép được thực hiện hoàn toàn trên server của Google, giúp tiết kiệm băng thông và thời gian.

## ✨ Tính năng
- **Server-side Copy**: Google tự nhân bản file trên hệ thống của họ, tốc độ cực nhanh.
- **Recursive Copy**: Tự động quét và sao chép toàn bộ thư mục con và cấu trúc bên trong.
- **An toàn**: Sử dụng thư viện chính chủ của Google API.

## 🚀 Hướng dẫn cài đặt

### 1. Cài đặt Python và Thư viện
Đảm bảo bạn đã cài đặt Python 3.10 trở lên. Sau đó chạy lệnh sau để cài đặt các thư viện cần thiết:

```bash
pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### 2. Thiết lập Google Drive API
Để chạy được script, bạn cần có file `credentials.json`:
1. Truy cập [Google Cloud Console](https://console.cloud.google.com/).
2. Tạo một Project mới.
3. Tìm kiếm và bật (Enable) **Google Drive API**.
4. Vào mục **Credentials** -> **Create Credentials** -> **OAuth client ID**.
5. Chọn loại ứng dụng là **Desktop App** và đặt tên bất kỳ.
6. Tải file JSON vừa tạo về máy.
7. Đổi tên file thành `credentials.json` và đặt vào cùng thư mục với script này.

## 💻 Cách sử dụng

1. Mở Terminal/Command Prompt tại thư mục dự án.
2. Chạy script bằng lệnh:
   ```bash
   python copy_drive.py
   ```
3. Trong lần đầu chạy, một trang trình duyệt sẽ hiện ra yêu cầu bạn đăng nhập và cấp quyền cho ứng dụng. Sau khi hoàn tất, file `token.json` sẽ được tạo ra để ghi nhớ đăng nhập cho lần sau.
4. Nhập **ID thư mục Nguồn** và **ID thư mục Đích** theo yêu cầu của script.
   - *ID là chuỗi ký tự nằm sau `folders/` trên thanh địa chỉ trình duyệt khi bạn mở thư mục đó trên Drive.*

## 📄 Giấy phép
Mã nguồn này được cung cấp cho mục đích học tập và sử dụng cá nhân.
