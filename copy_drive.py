import os.path

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
    source_folder = service.files().get(
        fileId=source_id,
        fields='name'
    ).execute()

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
    target_folder = service.files().create(
        body=file_metadata,
        fields='id'
    ).execute()

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

    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)"
    ).execute()

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
                service.files().copy(
                    fileId=item_id,
                    body=copy_metadata
                ).execute()

                print(f"✅ Copied: {item_name}")

            except HttpError as error:

                print(
                    f"❌ Lỗi copy file "
                    f"{item_name}: {error}"
                )


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