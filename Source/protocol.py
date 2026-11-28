import hashlib
import json
import os
import re
import socket
import tempfile
import uuid
from typing import Optional, Tuple

_WIN_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
_ACTIVE_ID_LOCKS = []

MAX_HEADER_BYTES = 4096
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_FORBIDDEN = ("|", "\n", "\r", " ", "\t")

SHORT_HELP_TEXT = (
    "Danh sách lệnh hỗ trợ:\n"
    "  /list                     - Xem danh sách peer đang online (STT, tên, IP, trạng thái)\n"
    "  /chat <tên|số|peer_id>    - Mở chat và kết nối TCP tới peer được chọn\n"
    "  /send <đường_dẫn_file>    - Gửi tệp/ảnh cho đối tác hiện tại\n"
    "  /transfers                - Xem danh sách tệp đang gửi/nhận kèm tiến độ\n"
    "  /cancel [send|recv|id]    - Hủy truyền tệp (tất cả, chỉ gửi, chỉ nhận hoặc theo mã ID)\n"
    "  /leave                    - Đóng cuộc trò chuyện hiện tại (gửi BYE)\n"
    "  /reconnect [tên|số|id]    - Kết nối lại phiên TCP sau khi rời chat / mất kết nối\n"
    "  /status <online|away>     - Đổi trạng thái hiện diện (quảng bá qua UDP)\n"
    "  /help                     - Xem danh sách lệnh\n"
    "  /delete                   - Xóa lịch sử đoạn chat hiện tại\n"
    "  /clear                    - Xóa màn hình terminal\n"
    "  /quit                     - Thoát chương trình an toàn"
)

def generate_peer_id() -> str:
    return uuid.uuid4().hex[:12]

def validate_peer_name(name: str) -> bool:
    return bool(name and name.strip()) and not any(c in name for c in _FORBIDDEN)

def validate_peer_id(peer_id: str) -> bool:
    return validate_peer_name(peer_id) and len(peer_id) <= 64

validate_room_name = validate_peer_name

def _try_acquire_peer_lock(peer_id: str, lock_dir: Optional[str] = None) -> bool:
    base_dir = lock_dir or os.path.join(tempfile.gettempdir(), "lan_chat_peer_locks")
    try:
        os.makedirs(base_dir, exist_ok=True)
        lock_path = os.path.join(base_dir, f"{sanitize_token(peer_id)}.lock")
        fh = open(lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0, os.SEEK_END)
                if fh.tell() == 0:
                    fh.write(b"1")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        _ACTIVE_ID_LOCKS.append(fh)
        return True
    except OSError:
        return True

def _save_peer_store(config_path: str, store: dict) -> None:
    tmp = f"{config_path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path)
    except OSError:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

def load_or_create_peer_id(
    room: str, name: str, tcp_port: int = 0, config_path: Optional[str] = None, acquire_lock: bool = True
) -> str:
    config_path = config_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".peer_ids.json")
    store = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    store = loaded
        except (OSError, ValueError):
            pass

    base_key = f"{room}|{name}"
    existing = store.get(base_key)
    if not (isinstance(existing, str) and validate_peer_id(existing)):
        legacy_prefix = f"{room}|{name}|"
        migrated = next(
            (v for k, v in store.items() if k.startswith(legacy_prefix) and isinstance(v, str) and validate_peer_id(v)),
            None,
        )
        existing = migrated or generate_peer_id()
        store[base_key] = existing
        _save_peer_store(config_path, store)

    if not acquire_lock or _try_acquire_peer_lock(existing):
        return existing

    port_key = f"{room}|{name}|{tcp_port}" if tcp_port > 0 else f"{room}|{name}|{os.getpid()}"
    alt_id = store.get(port_key)
    if not (isinstance(alt_id, str) and validate_peer_id(alt_id)) or alt_id == existing or not _try_acquire_peer_lock(alt_id):
        alt_id = generate_peer_id()
        store[port_key] = alt_id
        _save_peer_store(config_path, store)
        _try_acquire_peer_lock(alt_id)
    return alt_id

def sanitize_filename(filepath: str) -> str:
    raw = str(filepath or "").strip()
    base = re.split(r"[/\\]", raw)[-1] if raw else ""
    cleaned = "".join("_" if (ord(ch) < 32 or ch in '<>:"/\\|?*') else ch for ch in base)
    cleaned = cleaned.strip(" .")
    if not cleaned or cleaned in (".", ".."):
        return "unnamed_file"
    stem, ext = os.path.splitext(cleaned)
    stem = stem.rstrip(" .") or "unnamed_file"
    if stem.upper() in _WIN_RESERVED_NAMES:
        stem = f"_{stem}"
    result = f"{stem}{ext}"
    if len(result) > 200:
        max_stem = max(1, 200 - len(ext))
        result = f"{stem[:max_stem]}{ext}"
    return result

def sanitize_token(value: str) -> str:
    for ch in ("|", "\n", "\r"):
        value = value.replace(ch, "")
    return value.strip()

def is_image_filename(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in IMAGE_EXTENSIONS

def compute_file_sha256(filepath: str, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()

def encode_hello(peer_id: str, name: str, tcp_port: int, status: str, room: str = "default") -> bytes:
    return f"HELLO|{sanitize_token(peer_id)}|{name}|{tcp_port}|{status}|{sanitize_token(room) or 'default'}".encode("utf-8")

def decode_hello(data: bytes) -> Optional[Tuple[str, str, int, str, str]]:
    try:
        parts = data.decode("utf-8").strip().split("|")
        if len(parts) != 6 or parts[0] != "HELLO":
            return None
        pid, name, port, status, room = parts[1], parts[2], int(parts[3]), parts[4], parts[5]
        if (validate_peer_id(pid) and validate_peer_name(name) and 1 <= port <= 65535
                and status in ("online", "away") and validate_room_name(room)):
            return pid, name, port, status, room
    except (UnicodeDecodeError, ValueError):
        pass
    return None

def encode_quit(peer_id: str, room: str = "default") -> bytes:
    return f"QUIT|{sanitize_token(peer_id)}|{sanitize_token(room) or 'default'}".encode("utf-8")

def decode_quit(data: bytes) -> Optional[Tuple[str, str]]:
    try:
        parts = data.decode("utf-8").strip().split("|")
        if len(parts) == 3 and parts[0] == "QUIT" and validate_peer_id(parts[1]) and validate_room_name(parts[2]):
            return parts[1], parts[2]
    except UnicodeDecodeError:
        pass
    return None

def _encode_ctrl(cmd: str, *fields: str) -> bytes:
    return (cmd + "|" + "|".join(sanitize_token(str(x)) for x in fields) + "\n").encode("utf-8")

def encode_chat_frame(peer_id: str, sender_name: str, text: str, msg_id: str = "", reply_to: str = "") -> bytes:
    payload = text.encode("utf-8")
    pid = sanitize_token(peer_id)
    fields = [pid, sanitize_token(sender_name) or pid[:4], str(len(payload)), sanitize_token(msg_id)]
    if sanitize_token(reply_to):
        fields.append(sanitize_token(reply_to))
    return _encode_ctrl("MSG", *fields) + payload

def encode_file_header(
    peer_id: str, sender_name: str, filepath: str, file_size: int, msg_id: str = "", sha256_hex: str = ""
) -> bytes:
    pid = sanitize_token(peer_id)
    fields = [pid, sanitize_token(sender_name) or pid[:4], sanitize_filename(filepath), str(file_size), sanitize_token(msg_id)]
    if sanitize_token(sha256_hex):
        fields.append(sanitize_token(sha256_hex).lower())
    return _encode_ctrl("FILE", *fields)

def encode_seen_frame(peer_id: str, last_msg_id: str) -> bytes:
    return _encode_ctrl("SEEN", peer_id, last_msg_id)

def encode_react_frame(peer_id: str, sender_name: str, msg_id: str, emoji: str) -> bytes:
    return _encode_ctrl("REACT", peer_id, sender_name or peer_id[:4], msg_id, emoji)

def encode_typing_frame(peer_id: str, is_typing: bool) -> bytes:
    return _encode_ctrl("TYPING", peer_id, "1" if is_typing else "0")

def encode_recall_frame(peer_id: str, msg_id: str) -> bytes:
    return _encode_ctrl("RECALL", peer_id, msg_id)

def encode_connect_frame(peer_id: str, sender_name: str, tcp_port: int = 0) -> bytes:
    fields = [peer_id, sender_name or peer_id[:4]]
    if tcp_port > 0:
        fields.append(str(tcp_port))
    return _encode_ctrl("CONNECT", *fields)

def encode_connect_ack_frame(peer_id: str, sender_name: str, tcp_port: int = 0, status: str = "online") -> bytes:
    fields = [peer_id, sender_name or peer_id[:4], str(max(int(tcp_port), 0)), status if status in ("online", "away") else "online"]
    return _encode_ctrl("CONNECT_ACK", *fields)

def encode_status_frame(peer_id: str, status: str) -> bytes:
    return _encode_ctrl("STATUS", peer_id, status if status in ("online", "away") else "online")

def encode_ping_frame(peer_id: str) -> bytes:
    return _encode_ctrl("PING", peer_id)

def encode_pong_frame(peer_id: str) -> bytes:
    return _encode_ctrl("PONG", peer_id)

def encode_bye_frame(peer_id: str, sender_name: str, reason: str = "") -> bytes:
    fields = [peer_id, sender_name or peer_id[:4]]
    if reason:
        fields.append(reason)
    return _encode_ctrl("BYE", *fields)

def recv_line(sock: socket.socket, max_len: int = MAX_HEADER_BYTES) -> str:
    buf = bytearray()
    while len(buf) < max_len:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("Peer closed connection while reading header")
        if ch == b"\n":
            return buf.decode("utf-8").rstrip("\r")
        buf.extend(ch)
    raise ValueError(f"Protocol error: Header exceeded {max_len} bytes")

def recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
    if not (0 <= num_bytes <= MAX_PAYLOAD_BYTES):
        raise ValueError(f"Invalid payload length: {num_bytes}")
    chunks, received = [], 0
    while received < num_bytes:
        chunk = sock.recv(min(65536, num_bytes - received))
        if not chunk:
            raise ConnectionError(f"Connection lost (received {received}/{num_bytes} bytes)")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)

def parse_header(header_line: str) -> Tuple[str, list]:
    parts = header_line.split("|")
    if not parts or not parts[0]:
        raise ValueError("Empty protocol header")
    return parts[0], parts[1:]
