"""
state.py - Phụ trách: Linh
Quản lý toàn bộ trạng thái dùng chung (Shared State) của ứng dụng P2P LAN Chat.
Sử dụng threading.Lock() để đảm bảo tính toàn vẹn dữ liệu (Thread-Safety) khi nhiều
luồng (Main UI, UDP Listener, Timeout Checker, TCP Receivers, File Senders) cùng truy cập.
"""
import threading
import time
from typing import Dict, List, Optional, Tuple


class AppState:
    def __init__(self, name: str, tcp_port: int):
        # Khóa chính bảo vệ toàn bộ thuộc tính bên dưới khỏi Race Condition
        self.lock = threading.Lock()

        # Thông tin định danh của chính máy này (Local Peer)
        self.my_name: str = name
        self.my_tcp_port: int = tcp_port
        self.my_status: str = "online"  # Giá trị hợp lệ: "online" | "away"
        self.running: bool = True       # Cờ điều khiển vòng lặp toàn bộ các luồng

        # Danh sách các peer đang online trên mạng LAN:
        # Cấu trúc: { peer_name: {"ip": str, "port": int, "status": str, "last_seen": float} }
        self.online_peers: Dict[str, dict] = {}

        # Tên người dùng đang mở cửa sổ chat cùng (None nếu đang ở sảnh chính)
        self.current_partner: Optional[str] = None

        # Lịch sử tin nhắn & sự kiện truyền file theo từng peer:
        # Cấu trúc: { peer_name: ["[Minh] Hello", "[Quan] Hi", "[*] Sent file.pdf", ...] }
        self.chat_history: Dict[str, List[str]] = {}

        # Bộ đếm số tin nhắn chưa đọc từ các peer không phải current_partner:
        # Cấu trúc: { peer_name: int }
        self.unread_counts: Dict[str, int] = {}

    # -------------------------------------------------------------------------
    # 1. Quản lý trạng thái bản thân (Local Peer)
    # -------------------------------------------------------------------------
    def stop(self) -> None:
        """Báo hiệu dừng toàn bộ các luồng nền khi người dùng /quit hoặc Ctrl+C."""
        with self.lock:
            self.running = False

    def is_running(self) -> bool:
        with self.lock:
            return self.running

    def set_status(self, status: str) -> None:
        """Cập nhật trạng thái online/away của bản thân."""
        with self.lock:
            self.my_status = status

    def get_my_info(self) -> Tuple[str, int, str]:
        """Lấy thông tin (tên, cổng TCP, trạng thái) để UDP Broadcaster phát đi."""
        with self.lock:
            return self.my_name, self.my_tcp_port, self.my_status

    # -------------------------------------------------------------------------
    # 2. Quản lý danh sách Peer Online (Phục vụ phân hệ UDP của TV2)
    # -------------------------------------------------------------------------
    def update_peer(self, name: str, ip: str, tcp_port: int, status: str) -> Tuple[bool, Optional[str]]:
        """
        Cập nhật thông tin peer khi nhận gói tin UDP HELLO.
        Trả về: (is_new, status_changed_to)
          - is_new = True nếu peer mới vừa lên mạng.
          - status_changed_to = status mới nếu peer vừa đổi từ online <-> away, ngược lại None.
        """
        with self.lock:
            is_new = name not in self.online_peers
            status_changed = None

            if not is_new:
                old_status = self.online_peers[name]["status"]
                if old_status != status:
                    status_changed = status

            self.online_peers[name] = {
                "ip": ip,
                "port": tcp_port,
                "status": status,
                "last_seen": time.time(),
            }
            return is_new, status_changed

    def remove_expired_peers(self, timeout_sec: float = 10.0) -> List[Tuple[str, bool]]:
        """
        Xóa các peer không gửi tín hiệu HELLO quá `timeout_sec` giây.
        Trả về danh sách các tuple (peer_name, was_current_partner) để UI thông báo.
        """
        now = time.time()
        expired_list: List[Tuple[str, bool]] = []

        with self.lock:
            for name, info in list(self.online_peers.items()):
                if now - info["last_seen"] > timeout_sec:
                    was_partner = (self.current_partner == name)
                    if was_partner:
                        self.current_partner = None
                    del self.online_peers[name]
                    expired_list.append((name, was_partner))

        return expired_list

    def get_peer_list(self) -> List[Tuple[str, dict, int]]:
        """
        Lấy bản sao an toàn của danh sách peer online để hiển thị lệnh /list.
        Trả về list các tuple: (name, info_dict, unread_count).
        """
        with self.lock:
            result = []
            for name, info in self.online_peers.items():
                unread = self.unread_counts.get(name, 0)
                result.append((name, dict(info), unread))
            return result

    def get_peer_by_identifier(self, identifier: str) -> Tuple[Optional[str], Optional[dict]]:
        """
        Tìm peer theo tên (ví dụ: 'Minh') hoặc số thứ tự (ví dụ: '1') trong /list.
        Trả về (peer_name, info_dict) hoặc (None, None) nếu không tìm thấy.
        """
        with self.lock:
            items = list(self.online_peers.items())
            if identifier.isdigit():
                idx = int(identifier) - 1
                if 0 <= idx < len(items):
                    name, info = items[idx]
                    return name, dict(info)
                return None, None

            if identifier in self.online_peers:
                return identifier, dict(self.online_peers[identifier])
            return None, None

    # -------------------------------------------------------------------------
    # 3. Quản lý phiên Chat & Lịch sử tin nhắn (Phục vụ UI và TCP của TV3)
    # -------------------------------------------------------------------------
    def set_current_partner(self, partner_name: Optional[str]) -> Tuple[int, List[str]]:
        """
        Chuyển đổi đối tượng chat hiện tại (khi gọi /chat <name> hoặc /leave).
        Nếu mở chat với một peer, xóa bộ đếm tin chưa đọc của peer đó và trả về lịch sử cũ.
        """
        with self.lock:
            self.current_partner = partner_name
            if partner_name:
                unread = self.unread_counts.pop(partner_name, 0)
                history = list(self.chat_history.get(partner_name, []))
                return unread, history
            return 0, []

    def get_current_partner(self) -> Optional[str]:
        """Lấy tên peer đang chat cùng (dùng để hiển thị prompt và định tuyến tin gửi)."""
        with self.lock:
            return self.current_partner

    def clear_partner_if_match(self, peer_name: str) -> bool:
        """
        Tự động thoát phiên chat nếu đối phương gửi gói BYE hoặc ngắt kết nối đột ngột.
        Trả về True nếu người dùng vừa bị thoát khỏi khung chat hiện tại.
        """
        with self.lock:
            if self.current_partner == peer_name:
                self.current_partner = None
                return True
            return False

    def record_incoming_message(self, sender: str, formatted_line: str) -> Tuple[bool, int]:
        """
        Lưu tin nhắn đến từ `sender`.
        Trả về: (is_active_chat, unread_count)
          - Nếu đang chat với `sender`: trả về (True, 0) để UI in thẳng nội dung tin nhắn.
          - Nếu đang chat với người khác (hoặc ở sảnh): tăng unread và trả về (False, unread).
        """
        with self.lock:
            self.chat_history.setdefault(sender, []).append(formatted_line)
            if self.current_partner == sender:
                return True, 0
            self.unread_counts[sender] = self.unread_counts.get(sender, 0) + 1
            return False, self.unread_counts[sender]

    def record_outgoing_message(self, partner: str, formatted_line: str) -> None:
        """Lưu tin nhắn mình vừa gửi đi vào lịch sử chat của `partner`."""
        with self.lock:
            self.chat_history.setdefault(partner, []).append(formatted_line)

    def record_system_event(self, peer_name: str, event_line: str) -> None:
        """Lưu các mốc sự kiện (gửi/nhận file) vào lịch sử của `peer_name`."""
        with self.lock:
            self.chat_history.setdefault(peer_name, []).append(event_line)