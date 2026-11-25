import os
import socket
import threading
from typing import Dict, Optional, Tuple

from protocol import (
    encode_bye_frame,
    encode_chat_frame,
    encode_file_header,
    parse_header,
    recv_exact,
    recv_line,
    sanitize_filename,
)

CHUNK_SIZE = 4096
CONNECT_TIMEOUT = 5.0


class TCPService:
    def __init__(self, state, ui, host: str = "0.0.0.0", download_dir: str = "downloads"):
        self.state = state
        self.ui = ui
        self.host = host
        self.download_dir = download_dir

        os.makedirs(self.download_dir, exist_ok=True)

        self._stop_event = threading.Event()
        self.server_sock: Optional[socket.socket] = None
        self._acceptor_thread: Optional[threading.Thread] = None

        # Quản lý kết nối chat đang mở: {peer_name: socket} và lock gửi riêng cho từng peer
        self._conn_lock = threading.Lock()
        self._chat_sockets: Dict[str, socket.socket] = {}
        self._send_locks: Dict[str, threading.Lock] = {}

    # =========================================================================
    # 1. KHỞI ĐỘNG & TẮT PHÂN HỆ TCP (GỌI TỪ main.py)
    # =========================================================================
    def start(self) -> None:
        """Mở TCP listening socket và khởi chạy luồng tcp_acceptor."""
        _, my_tcp_port, _ = self.state.get_my_info()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, my_tcp_port))
        self.server_sock.listen(10)
        self.server_sock.settimeout(0.5)

        self._acceptor_thread = threading.Thread(
            target=self._acceptor_loop, name="tcp-acceptor", daemon=True
        )
        self._acceptor_thread.start()
        self.ui.show_message(f"[*] Listening on TCP port {my_tcp_port}")

    def shutdown(self) -> None:
        """Gửi BYE tới mọi peer đang kết nối và đóng toàn bộ socket an toàn."""
        self._stop_event.set()
        my_name, _, _ = self.state.get_my_info()
        bye_frame = encode_bye_frame(my_name)

        with self._conn_lock:
            peers = list(self._chat_sockets.items())
            self._chat_sockets.clear()
            self._send_locks.clear()

        for _, sock in peers:
            try:
                sock.sendall(bye_frame)
            except OSError:
                pass
            finally:
                self._safe_close(sock)

        if self.server_sock:
            self._safe_close(self.server_sock)
            self.server_sock = None

        if self._acceptor_thread and self._acceptor_thread.is_alive():
            self._acceptor_thread.join(timeout=1.0)

    def _acceptor_loop(self) -> None:
        """Chờ kết nối TCP đến và tạo 1 luồng receiver riêng cho mỗi kết nối."""
        while not self._stop_event.is_set() and self.state.is_running() and self.server_sock:
            try:
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            worker = threading.Thread(
                target=self._receiver_loop,
                args=(conn, addr, None),
                daemon=True,
            )
            worker.start()

    # =========================================================================
    # 2. LUỒNG NHẬN DỮ LIỆU (TCP RECEIVER - 1 THREAD / CONNECTION)
    # =========================================================================
    def _receiver_loop(
        self,
        conn: socket.socket,
        addr: Tuple[str, int],
        known_peer: Optional[str] = None,
    ) -> None:
        peer_name = known_peer
        is_chat_conn = known_peer is not None

        try:
            while not self._stop_event.is_set() and self.state.is_running():
                header_line = recv_line(conn)
                msg_type, args = parse_header(header_line)

                # --- NHÁNH 1: TIN NHẮN CHAT (MSG|<sender>|<byte_len>\n<payload>) ---
                if msg_type == "MSG":
                    if len(args) != 2:
                        break
                    sender, length_str = args
                    byte_len = int(length_str)

                    peer_name = sender
                    if not is_chat_conn:
                        is_chat_conn = True
                        self._register_chat_socket(sender, conn)

                    payload = recv_exact(conn, byte_len) if byte_len > 0 else b""
                    text = payload.decode("utf-8", errors="replace")
                    self._on_chat_message(sender, text)

                # --- NHÁNH 2: NHẬN FILE (FILE|<sender>|<filename>|<file_size>\n<bytes>) ---
                elif msg_type == "FILE":
                    if len(args) != 3:
                        break
                    sender, raw_filename, size_str = args
                    file_size = int(size_str)
                    if file_size < 0:
                        break

                    self._handle_receive_file(conn, sender, raw_filename, file_size)
                    # Mỗi file dùng 1 kết nối TCP riêng -> nhận xong thoát vòng lặp để đóng socket
                    break

                # --- NHÁNH 3: ĐỐI TÁC RỜI CHAT (BYE|<sender>\n) ---
                elif msg_type == "BYE":
                    sender = args[0] if args else peer_name
                    if sender:
                        self._handle_peer_disconnect(sender, conn, graceful=True)
                    break

                # --- GÓI TIN SAI ĐỊNH DẠNG ---
                else:
                    break

        except (ConnectionError, ValueError, OSError):
            if is_chat_conn and peer_name and not self._stop_event.is_set() and self.state.is_running():
                self._handle_peer_disconnect(peer_name, conn, graceful=False)
        finally:
            if is_chat_conn and peer_name:
                self._unregister_chat_socket(peer_name, conn)
            self._safe_close(conn)

    def _on_chat_message(self, sender: str, text: str) -> None:
        """Hiển thị ngay nếu đang chat với sender, ngược lại lưu unread và báo số tin chưa đọc."""
        formatted = f"[{sender}] {text}"
        is_active, unread_count = self.state.record_incoming_message(sender, formatted)
        if is_active:
            self.ui.show_message(formatted)
        else:
            self.ui.show_message(f"[*] New message from {sender} ({unread_count} unread)")

    def _handle_peer_disconnect(
        self, peer_name: str, conn: socket.socket, graceful: bool
    ) -> None:
        """Xử lý khi đối tác /leave hoặc crash giữa chừng."""
        removed = self._unregister_chat_socket(peer_name, conn)
        if not removed:
            return

        was_partner = self.state.clear_partner_if_match(peer_name)
        if graceful:
            self.ui.show_message(f"[*] {peer_name} left the chat.")
        else:
            self.ui.show_message(f"[*] Connection lost with {peer_name}.")

        if was_partner:
            self.ui.show_message("[*] Returned to main prompt.")

    # =========================================================================
    # 3. NGHIỆP VỤ CHAT & ĐÓNG CHAT (GỌI TỪ ui.py)
    # =========================================================================
    def _ensure_chat_connection(
        self, partner: str
    ) -> Tuple[Optional[socket.socket], Optional[threading.Lock]]:
        """Lấy kết nối chat có sẵn với partner, hoặc mở kết nối TCP mới nếu chưa có."""
        sock, send_lock = self._get_chat_socket_and_lock(partner)
        if sock and send_lock:
            return sock, send_lock

        peer_name, peer_info = self.state.get_peer_by_identifier(partner)
        if not peer_name or not peer_info:
            self.ui.show_message(f"[!] {partner} is offline.")
            return None, None

        ip, port = peer_info["ip"], peer_info["port"]
        try:
            new_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            new_sock.settimeout(CONNECT_TIMEOUT)
            new_sock.connect((ip, port))
            new_sock.settimeout(None)
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            self.ui.show_message(f"[!] Cannot connect to {peer_name} ({ip}:{port}): {exc}")
            return None, None

        self._register_chat_socket(peer_name, new_sock)
        worker = threading.Thread(
            target=self._receiver_loop,
            args=(new_sock, (ip, port), peer_name),
            daemon=True,
        )
        worker.start()

        return self._get_chat_socket_and_lock(peer_name)

    def send_message(self, partner: str, text: str) -> bool:
        """Đóng gói MSG frame và gửi tới đối tác đang chat."""
        sock, send_lock = self._ensure_chat_connection(partner)
        if not sock or not send_lock:
            return False

        my_name, _, _ = self.state.get_my_info()
        frame = encode_chat_frame(my_name, text)
        try:
            with send_lock:
                sock.sendall(frame)
            return True
        except OSError:
            self._handle_peer_disconnect(partner, sock, graceful=False)
            self._safe_close(sock)
            return False

    def close_chat(self, partner: str) -> None:
        """Gửi BYE frame và đóng kết nối TCP với partner (khi người dùng gõ /leave)."""
        sock, send_lock = self._get_chat_socket_and_lock(partner)
        if not sock or not send_lock:
            return

        my_name, _, _ = self.state.get_my_info()
        try:
            with send_lock:
                sock.sendall(encode_bye_frame(my_name))
        except OSError:
            pass
        finally:
            self._unregister_chat_socket(partner, sock)
            self._safe_close(sock)

    # =========================================================================
    # 4. TRUYỀN FILE ĐA LUỒNG (GỌI TỪ ui.py KHI GÕ /send <filepath>)
    # =========================================================================
    def send_file_async(self, partner: str, filepath: str) -> None:
        """Tạo luồng File Sender riêng để gửi file không làm đứng luồng chat."""
        peer_name, peer_info = self.state.get_peer_by_identifier(partner)
        if not peer_name or not peer_info:
            self.ui.show_message(f"[!] {partner} is offline. Cannot send file.")
            return

        worker = threading.Thread(
            target=self._file_sender_worker,
            args=(peer_name, peer_info["ip"], peer_info["port"], filepath),
            name=f"file-sender-{os.path.basename(filepath)}",
            daemon=True,
        )
        worker.start()

    def _file_sender_worker(
        self, partner: str, ip: str, port: int, filepath: str
    ) -> None:
        """Mở kết nối TCP riêng, gửi FILE header + từng chunk và báo % tiến độ."""
        my_name, _, _ = self.state.get_my_info()
        filename = sanitize_filename(filepath)
        file_size = os.path.getsize(filepath)
        sock: Optional[socket.socket] = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((ip, port))
            sock.settimeout(None)

            header = encode_file_header(my_name, filepath, file_size)
            sock.sendall(header)

            size_str = self._format_size(file_size)
            self.ui.show_message(f"[*] Sending {filename} ({size_str}) to {partner}...")

            if file_size == 0:
                done_msg = f"[*] Sent {filename} to {partner} (100% Done)."
                self.state.record_system_event(partner, done_msg)
                self.ui.show_message(done_msg)
                return

            sent_bytes = 0
            next_milestone = 25
            with open(filepath, "rb") as f:
                while not self._stop_event.is_set() and self.state.is_running():
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    sent_bytes += len(chunk)

                    percent = int((sent_bytes * 100) / file_size)
                    while next_milestone <= percent and next_milestone < 100:
                        self.ui.show_message(f"[*] Sending {filename} ... {next_milestone}%")
                        next_milestone += 25


            if sent_bytes == file_size:
                done_msg = f"[*] Sent {filename} ({size_str}) to {partner} — 100% Done."
                self.state.record_system_event(partner, done_msg)
                self.ui.show_message(done_msg)
            else:
                self.ui.show_message(f"[!] File transfer cancelled ({filename} -> {partner}).")
        except (socket.timeout, ConnectionRefusedError, BrokenPipeError, OSError) as exc:
            self.ui.show_message(f"[!] File transfer failed ({filename} -> {partner}): {exc}")
        finally:
            if sock:
                self._safe_close(sock)

    def _handle_receive_file(
        self, conn: socket.socket, sender: str, raw_filename: str, file_size: int
    ) -> None:
        """Nhận file lưu tạm .part vào downloads/, hoàn tất thì đổi tên, lỗi thì xóa .part."""
        safe_name = sanitize_filename(raw_filename)
        dest_path = self._unique_download_path(safe_name)
        part_path = dest_path + ".part"
        size_str = self._format_size(file_size)

        self.ui.show_message(f"[*] Receiving {safe_name} ({size_str}) from {sender}...")

        received = 0
        try:
            with open(part_path, "wb") as f:
                while received < file_size:
                    to_read = min(CHUNK_SIZE, file_size - received)
                    chunk = conn.recv(to_read)
                    if not chunk:
                        raise ConnectionError("Sender disconnected before transfer completed")
                    f.write(chunk)
                    received += len(chunk)

            os.replace(part_path, dest_path)
            saved_msg = f"[*] File received from {sender}: {dest_path} ({size_str})"
            self.state.record_system_event(sender, saved_msg)
            self.ui.show_message(saved_msg)

        except (OSError, ConnectionError) as exc:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            self.ui.show_message(
                f"[!] File receive interrupted ({safe_name} from {sender}): {exc}. Partial file deleted."
            )

    # =========================================================================
    # 5. HÀM HỖ TRỢ NỘI BỘ (THREAD-SAFE HELPERS)
    # =========================================================================
    def _register_chat_socket(self, peer_name: str, sock: socket.socket) -> None:
        with self._conn_lock:
            old = self._chat_sockets.get(peer_name)
            if old and old is not sock:
                self._safe_close(old)
            self._chat_sockets[peer_name] = sock
            self._send_locks[peer_name] = threading.Lock()

    def _unregister_chat_socket(self, peer_name: str, sock: socket.socket) -> bool:
        with self._conn_lock:
            if self._chat_sockets.get(peer_name) is sock:
                del self._chat_sockets[peer_name]
                self._send_locks.pop(peer_name, None)
                return True
            return False

    def _get_chat_socket_and_lock(
        self, peer_name: str
    ) -> Tuple[Optional[socket.socket], Optional[threading.Lock]]:
        with self._conn_lock:
            return self._chat_sockets.get(peer_name), self._send_locks.get(peer_name)

    def _unique_download_path(self, filename: str) -> str:
        """Tránh ghi đè nếu trong downloads/ đã có file trùng tên."""
        base_path = os.path.join(self.download_dir, filename)
        if not os.path.exists(base_path):
            return base_path
        stem, ext = os.path.splitext(filename)
        idx = 1
        while True:
            candidate = os.path.join(self.download_dir, f"{stem}({idx}){ext}")
            if not os.path.exists(candidate):
                return candidate
            idx += 1

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @staticmethod
    def _safe_close(sock: socket.socket) -> None:
        try:
            sock.close()
        except OSError:
            pass