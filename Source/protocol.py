"""
protocol.py - Phụ trách: Thành viên 1
Định nghĩa giao thức tầng ứng dụng (Application-Layer Protocol) & cơ chế đóng khung dữ liệu (TCP Framing).

1. Giao thức UDP (Discovery & Status):
   HELLO|<name>|<tcp_port>|<status>
   Ví dụ: HELLO|Quan|5000|online

2. Giao thức TCP (Reliable Stream Framing):
   - Tin nhắn chat : MSG|<sender>|<byte_len>\n<utf-8 payload>
   - Truyền file   : FILE|<sender>|<filename>|<file_size>\n<raw binary bytes>
   - Đóng phiên    : BYE|<sender>\n
"""
import os
import socket
from typing import Optional, Tuple

# Giới hạn an toàn để chống tràn bộ nhớ khi nhận gói tin lỗi/rác
MAX_HEADER_BYTES = 4096
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # Giới hạn tối đa 10 MB cho một tin nhắn text


# =============================================================================
# 1. CÁC HÀM KIỂM TRA TÍNH HỢP LỆ (VALIDATION & SANITIZATION)
# =============================================================================
def validate_peer_name(name: str) -> bool:
    """
    Kiểm tra tên người dùng hợp lệ:
    - Không được rỗng hoặc chỉ chứa khoảng trắng.
    - Không chứa ký tự phân cách giao thức ('|', '\\n', '\\r') hay dấu cách.
    """
    if not name or not name.strip():
        return False
    forbidden = ("|", "\n", "\r", " ", "\t")
    return not any(ch in name for ch in forbidden)


def sanitize_filename(filepath: str) -> str:
    """
    Lấy tên file gốc và loại bỏ các ký tự có thể làm hỏng header giao thức ('|', '\\n', '\\r')
    cũng như ngăn chặn lỗi Path Traversal (ví dụ: ../../etc/passwd).
    """
    base = os.path.basename(filepath)
    for ch in ("|", "\n", "\r"):
        base = base.replace(ch, "_")
    return base or "unnamed_file"


# =============================================================================
# 2. GIAO THỨC UDP (DISCOVERY & STATUS)
# =============================================================================
def encode_hello(name: str, tcp_port: int, status: str) -> bytes:
    """Đóng gói bản tin quảng bá sự hiện diện (UDP Presence Broadcast)."""
    return f"HELLO|{name}|{tcp_port}|{status}".encode("utf-8")


def decode_hello(data: bytes) -> Optional[Tuple[str, int, str]]:
    """
    Giải mã gói tin UDP nhận được.
    Trả về tuple (name, tcp_port, status) nếu hợp lệ, ngược lại trả về None.
    """
    try:
        text = data.decode("utf-8").strip()
        parts = text.split("|")
        if len(parts) != 4 or parts[0] != "HELLO":
            return None

        name = parts[1]
        tcp_port = int(parts[2])
        status = parts[3]

        if not validate_peer_name(name):
            return None
        if not (1 <= tcp_port <= 65535):
            return None
        if status not in ("online", "away"):
            return None

        return name, tcp_port, status
    except (UnicodeDecodeError, ValueError):
        return None


# =============================================================================
# 3. GIAO THỨC TCP (FRAMING & CODEC)
# =============================================================================
def encode_chat_frame(sender: str, text: str) -> bytes:
    """
    Đóng gói tin nhắn chat thành frame nhị phân hoàn chỉnh:
    Header: MSG|<sender>|<byte_len>\n
    Body  : <payload utf-8>
    """
    payload = text.encode("utf-8")
    header = f"MSG|{sender}|{len(payload)}\n".encode("utf-8")
    return header + payload


def encode_file_header(sender: str, filepath: str, file_size: int) -> bytes:
    """
    Đóng gói phần header cho luồng truyền file (phần nội dung file sẽ được TV3 đọc
    và gửi theo từng chunk để tiết kiệm RAM).
    Header: FILE|<sender>|<safe_filename>|<file_size>\n
    """
    safe_name = sanitize_filename(filepath)
    return f"FILE|{sender}|{safe_name}|{file_size}\n".encode("utf-8")


def encode_bye_frame(sender: str) -> bytes:
    """Đóng gói thông báo kết thúc phiên chat."""
    return f"BYE|{sender}\n".encode("utf-8")


# =============================================================================
# 4. CÁC HÀM ĐỌC/GỬI SOCKET MỨC THẤP (XỬ LÝ PHÂN MẢNH LUỒNG BYTE TCP)
# =============================================================================
def recv_line(sock: socket.socket, max_len: int = MAX_HEADER_BYTES) -> str:
    """
    Đọc từng byte từ socket TCP cho tới khi gặp ký tự kết thúc dòng '\\n'.
    Dùng để tách chính xác phần Header ra khỏi phần Payload phía sau.
    """
    buf = bytearray()
    while len(buf) < max_len:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("Peer closed connection while reading header")
        if ch == b"\n":
            return buf.decode("utf-8")
        buf.extend(ch)
    raise ValueError(f"Protocol error: Header exceeded {max_len} bytes")


def recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
    """
    Lặp lệnh recv() cho đến khi gom đủ chính xác `num_bytes` từ luồng TCP.
    Giải quyết triệt để hiện tượng phân mảnh/gộp gói tin (TCP Stream Framing).
    """
    if num_bytes < 0 or num_bytes > MAX_PAYLOAD_BYTES:
        raise ValueError(f"Invalid payload length: {num_bytes}")

    chunks = []
    received = 0
    while received < num_bytes:
        # Đọc tối đa 64KB mỗi lần hoặc đúng số byte còn thiếu
        to_read = min(65536, num_bytes - received)
        chunk = sock.recv(to_read)
        if not chunk:
            raise ConnectionError(f"Connection lost (received {received}/{num_bytes} bytes)")
        chunks.append(chunk)
        received += len(chunk)

    return b"".join(chunks)


def parse_header(header_line: str) -> Tuple[str, list]:
    """
    Phân tích chuỗi header nhận được từ recv_line().
    Trả về (msg_type, danh_sach_tham_so).
    """
    parts = header_line.split("|")
    if not parts or not parts[0]:
        raise ValueError("Empty protocol header")
    return parts[0], parts[1:]