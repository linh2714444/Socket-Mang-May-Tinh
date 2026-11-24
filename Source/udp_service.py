import socket
import threading
import time
from typing import List

from protocol import decode_hello, encode_hello


class UDPService:
    """Phân hệ UDP Discovery & Trạng thái (Phụ trách: Thành viên 2)."""

    def __init__(
        self,
        state,
        ui,
        udp_port: int = 9999,
        bcast_addr: str = "255.255.255.255",
        broadcast_interval: float = 3.0,
        timeout_sec: float = 10.0,
    ):
        self.state = state
        self.ui = ui
        self.udp_port = udp_port
        self.bcast_addr = bcast_addr
        self.broadcast_interval = broadcast_interval
        self.timeout_sec = timeout_sec

        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._last_sent_status = None

        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        try:
            self.send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass

            self.recv_sock.bind(("", self.udp_port))
            self.recv_sock.settimeout(0.5)
        except OSError:
            self.send_sock.close()
            self.recv_sock.close()
            raise

    def _send_hello(self) -> None:
        name, tcp_port, status = self.state.get_my_info()
        payload = encode_hello(name, tcp_port, status)
        try:
            self.send_sock.sendto(payload, (self.bcast_addr, self.udp_port))
        except OSError as exc:
            if not self._stop_event.is_set() and self.state.is_running():
                self.ui.show_message(f"[!] UDP broadcast error: {exc}")

    def _is_own_packet(self, name: str, tcp_port: int) -> bool:
        my_name, my_tcp_port, _ = self.state.get_my_info()
        return name == my_name and tcp_port == my_tcp_port

    def _broadcaster_loop(self) -> None:
        last_sent = 0.0
        while not self._stop_event.is_set() and self.state.is_running():
            _, _, status = self.state.get_my_info()
            now = time.time()
            # Gửi ngay khi đổi trạng thái online/away, hoặc định kỳ mỗi 3 giây
            if status != self._last_sent_status or (now - last_sent) >= self.broadcast_interval:
                self._send_hello()
                self._last_sent_status = status
                last_sent = now
            self._stop_event.wait(0.2)

    def _listener_loop(self) -> None:
        while not self._stop_event.is_set() and self.state.is_running():
            try:
                data, addr = self.recv_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            decoded = decode_hello(data)
            if not decoded:
                continue

            peer_name, peer_tcp_port, peer_status = decoded
            if self._is_own_packet(peer_name, peer_tcp_port):
                continue

            sender_ip = addr[0]
            is_new, status_changed = self.state.update_peer(
                peer_name, sender_ip, peer_tcp_port, peer_status
            )
            if is_new:
                self.ui.show_message(
                    f"[+] {peer_name} ({sender_ip}:{peer_tcp_port}) is {peer_status}."
                )
            elif status_changed:
                self.ui.show_message(f"[*] {peer_name} is now {status_changed}.")

    def _timeout_loop(self) -> None:
        while not self._stop_event.is_set() and self.state.is_running():
            self._stop_event.wait(1.0)
            if self._stop_event.is_set() or not self.state.is_running():
                break

            expired = self.state.remove_expired_peers(timeout_sec=self.timeout_sec)
            for peer_name, was_partner in expired:
                self.ui.show_message(f"[-] {peer_name} is offline (timeout).")
                if was_partner:
                    self.ui.show_message(f"[!] Active chat closed because {peer_name} went offline.")

    def start(self) -> None:
        workers = [
            ("udp-broadcaster", self._broadcaster_loop),
            ("udp-listener", self._listener_loop),
            ("udp-timeout-checker", self._timeout_loop),
        ]
        for thread_name, target_fn in workers:
            thread = threading.Thread(target=target_fn, name=thread_name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def shutdown(self) -> None:
        self._stop_event.set()
        for sock in (self.send_sock, self.recv_sock):
            try:
                sock.close()
            except OSError:
                pass
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=1.0)