import socket
import threading
import time
from typing import Callable, List, Optional

from protocol import decode_hello, decode_quit, encode_hello, encode_quit

class UDPService:
    def __init__(
        self, state, ui, udp_port: int = 9999, bcast_addr: str = "255.255.255.255",
        broadcast_interval: float = 3.0, timeout_sec: float = 10.0,
        room: Optional[str] = None, on_peer_timeout: Optional[Callable[[str], None]] = None,
    ):
        self.state, self.ui = state, ui
        self.udp_port, self.bcast_addr = udp_port, bcast_addr
        self.broadcast_interval, self.timeout_sec = broadcast_interval, timeout_sec
        self.room = room or getattr(state, "my_room", "default")
        self.on_peer_timeout = on_peer_timeout

        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._last_sent_status = None
        self._broadcast_failed = False

        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._lan_send_sock: Optional[socket.socket] = None
        self._lan_ip: str = ""
        try:
            self.send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.send_sock.bind(("", 0))
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
        self._refresh_lan_send_sock()

    @staticmethod
    def _detect_primary_lan_ip() -> str:
        for probe in (("8.8.8.8", 80), ("10.255.255.255", 1)):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(probe)
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                    return ip
            except OSError:
                continue
            finally:
                s.close()
        return ""

    def _refresh_lan_send_sock(self) -> None:
        if self.bcast_addr != "255.255.255.255":
            return
        lan_ip = self._detect_primary_lan_ip()
        if lan_ip == self._lan_ip:
            return
        if self._lan_send_sock is not None:
            try:
                self._lan_send_sock.close()
            except OSError:
                pass
            self._lan_send_sock = None
        self._lan_ip = lan_ip
        if not lan_ip:
            return
        try:
            ls = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            ls.bind((lan_ip, 0))
            self._lan_send_sock = ls
        except OSError:
            self._lan_send_sock = None
            self._lan_ip = ""

    def _send_hello(self) -> None:
        pid, name, tcp_port, status = self.state.get_my_info()
        payload = encode_hello(pid, name, tcp_port, status, room=self.room)
        if self.bcast_addr == "255.255.255.255":
            self._refresh_lan_send_sock()
        sent_ok, last_exc = False, None
        for sock in self._active_send_sockets():
            try:
                sock.sendto(payload, (self.bcast_addr, self.udp_port))
                sent_ok = True
            except OSError as exc:
                last_exc = exc

        if sent_ok:
            if self._broadcast_failed:
                self._broadcast_failed = False
                self.ui.show_message("[*] UDP broadcast recovered.")
            return

        if self.bcast_addr == "255.255.255.255":
            try:
                self.send_sock.sendto(payload, ("127.255.255.255", self.udp_port))
                if not self._broadcast_failed and not self._stop_event.is_set() and self.state.is_running():
                    self._broadcast_failed = True
                    self.ui.show_message("[*] Network unavailable — switched UDP discovery to loopback (127.255.255.255).")
                return
            except OSError:
                pass
        if not self._broadcast_failed and not self._stop_event.is_set() and self.state.is_running():
            self._broadcast_failed = True
            self.ui.show_message(f"[!] UDP broadcast error (network unavailable?): {last_exc}")

    def _broadcaster_loop(self) -> None:
        last_sent = 0.0
        while not self._stop_event.is_set() and self.state.is_running():
            status = self.state.get_my_info()[3]
            now = time.time()
            if status != self._last_sent_status or (now - last_sent) >= self.broadcast_interval:
                self._send_hello()
                self._last_sent_status, last_sent = status, now
            self._stop_event.wait(0.2)

    def _listener_loop(self) -> None:
        my_pid = self.state.my_peer_id
        while not self._stop_event.is_set() and self.state.is_running():
            try:
                data, addr = self.recv_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            quit_pkt = decode_quit(data)
            if quit_pkt:
                qpid, qroom = quit_pkt
                if qpid != my_pid and qroom == self.room:
                    pname = self.state.get_peer_name(qpid)
                    was_online = self.state.mark_peer_offline(qpid, clear_endpoint=True)
                    was_conn = self.state.get_session_state(qpid) == "connected"
                    self._handle_peer_gone(qpid, pname, "exited the app.", show_log=(was_online or was_conn), mark_disc=was_conn)
                continue

            decoded = decode_hello(data)
            if not decoded or decoded[0] == my_pid or decoded[4] != self.room:
                continue
            pid, pname, port, status, room = decoded
            is_new, status_changed = self.state.update_peer(pid, pname, addr[0], port, status)
            if is_new:
                self.ui.show_message(f"[+] {pname} [#{pid[:4]}] ({addr[0]}:{port}) joined room '{room}' [{status}].")
            elif status_changed:
                self.ui.show_message(f"[*] {pname} [#{pid[:4]}] is now {status_changed}.")

    def _handle_peer_gone(self, pid: str, pname: str, reason: str, show_log: bool = True, mark_disc: bool = False) -> None:
        if self.on_peer_timeout:
            self.on_peer_timeout(pid)
        if show_log:
            self.ui.show_message(f"[-] {pname} [#{pid[:4]}] {reason}")
        if mark_disc and not self.state.is_session_disconnected(pid):
            self.state.set_session_state(pid, "disconnected")
            self.state.record_divider(pid, f"{pname} disconnected", tone="danger")
            self.ui.show_message(f"──────── {pname} [#{pid[:4]}] disconnected ────────")

    def _timeout_loop(self) -> None:
        while not self._stop_event.wait(1.0) and self.state.is_running():
            self.state.cleanup_expired_typing()
            for pid, pname, was_partner in self.state.remove_expired_peers(timeout_sec=self.timeout_sec):
                was_conn = self.state.get_session_state(pid) == "connected"
                self._handle_peer_gone(pid, pname, "is offline (timeout).", mark_disc=(was_partner or was_conn))

    def _active_send_sockets(self) -> List[socket.socket]:
        return [self.send_sock] + ([self._lan_send_sock] if self._lan_send_sock else [])

    def start(self) -> None:
        for name, fn in (("udp-broadcaster", self._broadcaster_loop), ("udp-listener", self._listener_loop), ("udp-timeout-checker", self._timeout_loop)):
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def _send_quit(self) -> None:
        payload = encode_quit(self.state.my_peer_id, room=self.room)
        targets = [(self.bcast_addr, self.udp_port)]
        if self.bcast_addr == "255.255.255.255":
            targets.append(("127.255.255.255", self.udp_port))
        for _ in range(2):
            for sock in self._active_send_sockets():
                for addr in targets:
                    try:
                        sock.sendto(payload, addr)
                    except OSError:
                        pass

    def shutdown(self) -> None:
        self._stop_event.set()
        self._send_quit()
        for s in (self.send_sock, self.recv_sock, self._lan_send_sock):
            if s is None:
                continue
            try:
                s.close()
            except OSError:
                pass
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=1.0)
