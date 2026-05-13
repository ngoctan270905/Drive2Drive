import os.path
import time
import socket
import http.client

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# =========================================================
# GOOGLE DRIVE API SCOPES
# =========================================================
#
# Scope này cho phép:
# - đọc file/folder
# - tạo folder
# - copy file
# - thao tác toàn bộ Google Drive
#
# Nếu chỉ cần read-only thì có thể dùng:
# https://www.googleapis.com/auth/drive.readonly
#
# Nhưng ở đây cần copy file sang Drive đích
# nên cần quyền full drive.
#
# =========================================================
SCOPES = ['https://www.googleapis.com/auth/drive']


def execute_with_retry(request, max_retries=5):
    """
    Execute Google API request với cơ chế retry tự động.

    =====================================================
    Tại sao cần retry?
    =====================================================

    Khi xử lý số lượng lớn file/folder trên Google Drive,
    rất dễ gặp các lỗi tạm thời như:

    - mất mạng
    - DNS resolve fail
    - Google API timeout
    - rate limit
    - Google server lỗi tạm thời

    Ví dụ:
    -----------------------------------------------------
    socket.gaierror
    RemoteDisconnected
    HTTP 500
    HTTP 503
    HTTP 429

    Nếu không retry:
    -> script sẽ chết giữa chừng.

    =====================================================
    Cách hoạt động
    =====================================================

    1. Thử execute request
    2. Nếu thành công:
        -> return kết quả ngay
    3. Nếu lỗi mạng/server:
        -> sleep theo exponential backoff
        -> retry lại
    4. Nếu retry quá số lần:
        -> raise exception

    =====================================================
    Exponential Backoff
    =====================================================

    Retry lần:
    - 1 -> chờ 1s
    - 2 -> chờ 2s
    - 3 -> chờ 4s
    - 4 -> chờ 8s
    ...

    Điều này giúp:
    - giảm spam request
    - tăng khả năng recovery

    Args:
        request:
            Google API request object.

        max_retries (int):
            Số lần retry tối đa.

    Returns:
        Kết quả execute() của request.
    """

    for attempt in range(max_retries):

        try:
            return request.execute()

        except (
            HttpError,
            socket.gaierror,
            http.client.RemoteDisconnected,
            TimeoutError,
            ConnectionError,
        ) as error:

            # =============================================
            # Nếu là HttpError:
            # chỉ retry các lỗi server/network
            # =============================================
            if isinstance(error, HttpError):

                status = error.resp.status

                retryable_statuses = [
                    429,
                    500,
                    502,
                    503,
                    504
                ]

                # =========================================
                # Nếu không phải lỗi retry-able
                # -> throw luôn
                # =========================================
                if status not in retryable_statuses:
                    raise

            # =============================================
            # Exponential backoff
            # =============================================
            wait_time = 2 ** attempt

            print(
                f"⚠️ Lỗi mạng/API, "
                f"retry sau {wait_time}s "
                f"({attempt + 1}/{max_retries})"
            )

            time.sleep(wait_time)

    # =====================================================
    # Retry quá số lần cho phép
    # =====================================================
    raise Exception("❌ Retry quá số lần cho phép")


def get_service():
    """
    Khởi tạo Google Drive API service.

    Flow hoạt động:
    -----------------------------------------------------
    1. Kiểm tra token.json đã tồn tại chưa
    2. Nếu có:
        - load credentials cũ
    3. Nếu credentials hết hạn:
        - refresh token tự động
    4. Nếu chưa từng login:
        - mở browser OAuth login
    5. Sau khi login:
        - lưu token mới vào token.json
    6. Trả về Google Drive API service object

    Returns:
        googleapiclient.discovery.Resource:
            Drive API service dùng để gọi API.
    """

    creds = None

    # =====================================================
    # token.json chứa:
    # - access token
    # - refresh token
    #
    # File này được tạo sau lần login đầu tiên.
    #
    # Nếu file tồn tại:
    # -> load credentials cũ
    # =====================================================
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file(
            'token.json',
            SCOPES
        )

    # =====================================================
    # Nếu:
    # - chưa có creds
    # - hoặc creds không hợp lệ
    #
    # thì cần authenticate lại.
    # =====================================================
    if not creds or not creds.valid:

        # =================================================
        # Nếu token hết hạn nhưng còn refresh token:
        # -> refresh tự động
        #
        # Người dùng không cần login lại.
        # =================================================
        if creds and creds.expired and creds.refresh_token:

            print("Refreshing expired token...")
            creds.refresh(Request())

        else:
            # =============================================
            # Chưa từng login:
            # mở browser OAuth flow
            # =============================================
            print("Opening browser for Google login...")

            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json',
                SCOPES
            )

            creds = flow.run_local_server(port=0)

        # =================================================
        # Lưu token mới để các lần chạy sau
        # không cần login lại.
        # =================================================
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # =====================================================
    # Tạo Google Drive API service
    # =====================================================
    return build('drive', 'v3', credentials=creds)


def copy_folder(service, source_id, target_parent_id):
    """
    Sao chép thư mục Google Drive theo cách đệ quy.

    Hàm này:
    -----------------------------------------------------
    1. Tạo folder tương ứng ở Drive đích
    2. Liệt kê toàn bộ:
        - file
        - folder con
    3. Nếu là folder:
        - gọi lại chính hàm này (recursive)
    4. Nếu là file:
        - dùng Google server-side copy
          KHÔNG download về máy

    =====================================================
    Ưu điểm của server-side copy
    =====================================================

    - cực nhanh
    - không tốn bandwidth local
    - không tốn disk local
    - không cần download/upload lại

    Google copy trực tiếp bên trong hạ tầng của nó.

    =====================================================
    Retry Strategy
    =====================================================

    Các request API đều được wrap bằng:
        execute_with_retry()

    để tránh:
    - script chết giữa chừng
    - mất mạng tạm thời
    - API timeout

    =====================================================
    Xử lý lỗi 403
    =====================================================

    Một số file:
    - bị disable copy
    - chỉ có quyền viewer
    - policy Shared Drive chặn copy

    Khi đó:
        -> skip file
        -> tiếp tục script

    Args:
        service:
            Google Drive API service object.

        source_id (str):
            ID thư mục nguồn.

        target_parent_id (str):
            ID thư mục cha bên Drive đích.
    """

    # =====================================================
    # Lấy thông tin thư mục nguồn
    #
    # fields='name'
    # -> chỉ lấy tên để giảm payload API.
    # =====================================================
    source_folder = execute_with_retry(
        service.files().get(
            fileId=source_id,
            fields='name'
        )
    )

    source_name = source_folder.get('name')

    print(f"\n📁 Đang tạo thư mục: {source_name}")

    # =====================================================
    # Metadata folder mới bên Drive đích
    # =====================================================
    file_metadata = {
        'name': source_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [target_parent_id]
    }

    # =====================================================
    # Tạo folder mới
    # =====================================================
    target_folder = execute_with_retry(
        service.files().create(
            body=file_metadata,
            fields='id'
        )
    )

    # =====================================================
    # Lấy ID folder vừa tạo
    # =====================================================
    new_folder_id = target_folder.get('id')

    # =====================================================
    # Query lấy toàn bộ file/folder con
    #
    # trashed = false
    # -> bỏ qua file trong thùng rác
    # =====================================================
    query = f"'{source_id}' in parents and trashed = false"

    results = execute_with_retry(
        service.files().list(
            q=query,
            fields="files(id, name, mimeType)"
        )
    )

    items = results.get('files', [])

    # =====================================================
    # Duyệt toàn bộ item trong folder
    # =====================================================
    for item in items:

        item_id = item['id']
        item_name = item['name']
        mime_type = item['mimeType']

        # =================================================
        # Nếu là folder
        # -> gọi recursive
        # =================================================
        if mime_type == 'application/vnd.google-apps.folder':

            print(f"📂 Found subfolder: {item_name}")

            copy_folder(
                service,
                item_id,
                new_folder_id
            )

        else:
            # =============================================
            # Nếu là file:
            # dùng Google server-side copy
            #
            # KHÔNG:
            # - download
            # - upload
            #
            # Google copy nội bộ server của nó.
            # =============================================
            print(f"📄 Đang copy file: {item_name}")

            copy_metadata = {
                'name': item_name,
                'parents': [new_folder_id]
            }

            try:
                execute_with_retry(
                    service.files().copy(
                        fileId=item_id,
                        body=copy_metadata
                    )
                )

                print(f"✅ Copied: {item_name}")

            except HttpError as error:

                # =========================================
                # Một số file bị:
                # - disable copy
                # - viewer only
                # - restricted bởi owner/admin
                #
                # Khi đó:
                # -> skip file
                # -> tiếp tục script
                # =========================================
                if error.resp.status == 403:

                    print(
                        f"⏭️ Skip file không cho copy: "
                        f"{item_name}"
                    )

                    continue

                # =========================================
                # Lỗi HTTP khác
                # =========================================
                print(
                    f"❌ Lỗi copy file "
                    f"{item_name}: {error}"
                )

                continue

            except Exception as error:

                # =========================================
                # Các lỗi ngoài dự kiến:
                # - mạng
                # - DNS
                # - timeout
                # - connection reset
                # ...
                # =========================================
                print(
                    f"❌ Lỗi khác khi copy file "
                    f"{item_name}: {error}"
                )

                continue


def main():
    """
    Entry point chính của chương trình.

    Quy trình:
    -----------------------------------------------------
    1. Authenticate Google Drive API
    2. Nhập:
        - source folder ID
        - target folder ID
    3. Bắt đầu recursive copy
    4. Hiển thị trạng thái hoàn tất
    """

    # =====================================================
    # Khởi tạo Drive API service
    # =====================================================
    service = get_service()

    # =====================================================
    # Nhập folder nguồn
    # =====================================================
    source_folder_id = input(
        "Nhập ID thư mục NGUỒN: "
    ).strip()

    # =====================================================
    # Nhập folder đích
    #
    # Nếu để trống:
    # -> copy vào My Drive root
    # =====================================================
    target_parent_id = input(
        "Nhập ID thư mục ĐÍCH "
        "(để trống nếu muốn copy vào My Drive): "
    ).strip()

    if not target_parent_id:
        target_parent_id = 'root'

    print("\n--- Bắt đầu quá trình copy server-side ---")

    # =====================================================
    # Bắt đầu recursive copy
    # =====================================================
    copy_folder(
        service,
        source_folder_id,
        target_parent_id
    )

    print("\n--- Hoàn tất! ---")


# =========================================================
# Python entry point
#
# Chỉ chạy khi file được execute trực tiếp.
# =========================================================
if __name__ == '__main__':
    main()