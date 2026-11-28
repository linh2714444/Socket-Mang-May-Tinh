import hashlib
import os
import queue
import select
import socket
import sys
import threading
import time
from typing import Dict, Optional, Tuple

from protocol import (
    MAX_PAYLOAD_BYTES, compute_file_sha256, encode_bye_frame, encode_chat_frame,
    encode_connect_ack_frame, encode_connect_frame, encode_file_header, encode_ping_frame,
    encode_pong_frame, encode_react_frame, encode_recall_frame, encode_seen_frame,
    encode_status_frame, encode_typing_frame, is_image_filename, parse_header, recv_exact,
    recv_line, sanitize_filename, validate_peer_id, validate_peer_name,
)

CHUNK_SIZE = 16384
CONNECT_TIMEOUT = 2.5
HANDSHAKE_TIMEOUT = 15.0
SEND_TIMEOUT = 4.0
FILE_IO_TIMEOUT = 12.0
HEARTBEAT_INTERVAL = 4.0
HEARTBEAT_TIMEOUT = 11.0

class TCPService:
    def __init__(
        self, state, ui, host: str = "0.0.0.0", download_dir: str = "downloads", max_file_speed_mb: float = 0.0
    ):
        self.state, self.ui, self.host = state, ui, host
        self.max_file_speed_mb = max(float(max_file_speed_mb), 0.0)
        self.download_dir = os.path.abspath(download_dir)
        self.sent_dir = os.path.join(self.download_dir, "_sent")
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.sent_dir, exist_ok=True)

        self._stop_event = threading.Event()
        self.server_sock: Optional[socket.socket] = None
        self._acceptor_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._outbox_lock = threading.Lock()
        self._peer_outboxes: Dict[str, "queue.Queue[Optional[tuple]]"] = {}
        self._peer_workers: Dict[str, threading.Thread] = {}

        self._conn_lock = threading.Lock()
        self._chat_sockets: Dict[str, socket.socket] = {}
        self._send_locks: Dict[str, threading.Lock] = {}
        self._last_tcp_rx: Dict[str, float] = {}
        self._last_ping_sent: Dict[str, float] = {}

        self._transfer_lock = threading.Lock()
        self._transfer_cancels: Dict[str, threading.Event] = {}
        self._transfer_sockets: Dict[str, socket.socket] = {}
        self._transfer_meta: Dict[str, dict] = {}
        self._transfer_threads: Dict[str, threading.Thread] = {}

    def start(self) -> None:
        my_port = self.state.get_my_info()[2]
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif os.name != "nt":
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, my_port))
        self.server_sock.listen(16)
        self.server_sock.settimeout(0.5)

        self._acceptor_thread = threading.Thread(target=self._acceptor_loop, name="tcp-acceptor", daemon=True)
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="tcp-heartbeat", daemon=True)
        self._acceptor_thread.start()
        self._heartbeat_thread.start()
        self.ui.show_message(f"[*] Listening on TCP port {my_port}")

    def shutdown(self) -> None:
        self._stop_event.set()
        with self._outbox_lock:
            for q in self._peer_outboxes.values():
                q.put(None)
            sender_workers = list(self._peer_workers.values())
            self._peer_outboxes.clear()
            self._peer_workers.clear()
        self.cancel_active_transfers()
        with self._transfer_lock:
            active_t = list(self._transfer_threads.values())

        my_pid, my_name = self.state.get_my_info()[:2]
        bye_frame = encode_bye_frame(my_pid, my_name, reason="quit")
        with self._conn_lock:
            peers = list(self._chat_sockets.values())
            self._chat_sockets.clear()
            self._send_locks.clear()
            self._last_tcp_rx.clear()
            self._last_ping_sent.clear()

        for sock in peers:
            try:
                if sock.fileno() >= 0:
                    self._sendall_with_timeout(sock, bye_frame, timeout=1.0)
            except (OSError, ValueError):
                pass
            finally:
                self._safe_close(sock)

        if self.server_sock:
            self._safe_close(self.server_sock)
            self.server_sock = None

        for t in (self._acceptor_thread, self._heartbeat_thread, *sender_workers, *active_t):
            if t and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=1.0)

    def _acceptor_loop(self) -> None:
        while not self._stop_event.is_set() and self.state.is_running() and self.server_sock:
            try:
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._receiver_loop, args=(conn, addr, None), daemon=True).start()

    def _peer_sender_loop(self, pid: str, q: "queue.Queue[Optional[tuple]]") -> None:
        try:
            while not self._stop_event.is_set() and self.state.is_running():
                try:
                    item = q.get(timeout=10.0)
                except queue.Empty:
                    with self._outbox_lock:
                        if q.empty() and self._peer_outboxes.get(pid) is q:
                            del self._peer_outboxes[pid]
                            self._peer_workers.pop(pid, None)
                            break
                    continue
                if item is None:
                    break

                action = item[0]
                my_pid, my_name = self.state.get_my_info()[:2]
                if action == "MSG":
                    _, _, text, msg_id, reply_to = item
                    ok, err = self._send_frame_sync(pid, encode_chat_frame(my_pid, my_name, text, msg_id, reply_to))
                    if msg_id:
                        self.state.update_message_status(pid, msg_id, "sent" if ok else "failed", error="" if ok else err)
                elif action == "SEEN":
                    self._send_frame_sync(pid, encode_seen_frame(my_pid, item[2]), silent=True)
                elif action == "REACT":
                    self._send_frame_sync(pid, encode_react_frame(my_pid, my_name, item[2], item[3]))
                elif action == "TYPING":
                    self._send_frame_sync(pid, encode_typing_frame(my_pid, item[2]), silent=True)
                elif action == "RECALL":
                    self._send_frame_sync(pid, encode_recall_frame(my_pid, item[2]))
                elif action == "STATUS":
                    self._send_frame_sync(pid, encode_status_frame(my_pid, item[2]), auto_connect=False, silent=True)
                elif action == "PING":
                    self._send_frame_sync(pid, encode_ping_frame(my_pid), auto_connect=False, silent=True)
                elif action == "PONG":
                    self._send_frame_sync(pid, encode_pong_frame(my_pid), auto_connect=False, silent=True)
                elif action == "BYE":
                    self._close_chat_sync(pid)
        finally:
            with self._outbox_lock:
                if self._peer_outboxes.get(pid) is q:
                    del self._peer_outboxes[pid]
                if self._peer_workers.get(pid) is threading.current_thread():
                    del self._peer_workers[pid]

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(1.0) and self.state.is_running():
            now = time.time()
            with self._conn_lock:
                snap = [
                    (pid, sock, self._last_tcp_rx.get(pid, now), self._last_ping_sent.get(pid, 0.0))
                    for pid, sock in self._chat_sockets.items()
                ]
            for pid, sock, last_rx, last_ping in snap:
                if (now - last_rx) > HEARTBEAT_TIMEOUT:
                    self._handle_peer_disconnect(pid, sock)
                    self._safe_close(sock)
                elif (now - last_ping) >= HEARTBEAT_INTERVAL:
                    with self._conn_lock:
                        if self._chat_sockets.get(pid) is sock:
                            self._last_ping_sent[pid] = now
                    self._enqueue("PING", pid)

    def _receiver_loop(self, conn: socket.socket, addr: Tuple[str, int], known_peer_id: Optional[str] = None) -> None:
        peer_id, is_chat_conn = known_peer_id, known_peer_id is not None
        my_pid = self.state.my_peer_id

        if not is_chat_conn:
            try:
                conn.settimeout(HANDSHAKE_TIMEOUT)
            except OSError:
                pass

        def bind_chat(sid: str, sname: str = "", peer_port: int = 0, allow_new_endpoint: bool = False) -> None:
            nonlocal peer_id, is_chat_conn
            if not validate_peer_id(sid) or sid == my_pid:
                raise ValueError(f"Invalid peer_id '{sid[:24]}'")
            if sname and not validate_peer_name(sname):
                raise ValueError(f"Invalid peer_name '{sname[:24]}'")
            if is_chat_conn and peer_id and sid != peer_id:
                raise ConnectionError(f"Peer ID mismatch on chat socket: expected {peer_id[:4]}, got {sid[:4]}")
            if not is_chat_conn:
                known_ep = self.state.get_peer_endpoint(sid)
                if not known_ep:
                    if not (allow_new_endpoint and 1 <= peer_port <= 65535):
                        raise ValueError(f"Rejected unauthenticated packet from unknown peer '{sid[:12]}'")
                conn.settimeout(None)
                peer_id = sid
                self.state.touch_peer(sid, name=sname, ip=addr[0], tcp_port=peer_port)
                is_chat_conn = True
                self._enable_keepalive(conn)
                self._register_chat_socket(sid, conn)
            else:
                peer_id = sid
                self.state.touch_peer(sid, name=sname, ip=addr[0], tcp_port=peer_port)
                self._mark_tcp_rx(sid)

        try:
            while not self._stop_event.is_set() and self.state.is_running():
                header = recv_line(conn)
                mtype, args = parse_header(header)

                if mtype == "MSG" and len(args) >= 3:
                    sid, sname, blen = args[0], args[1], int(args[2])
                    if blen < 0 or blen > MAX_PAYLOAD_BYTES:
                        raise ValueError(f"Invalid MSG payload length: {blen}")
                    mid = args[3] if len(args) >= 4 else ""
                    rep = args[4] if len(args) >= 5 else ""
                    bind_chat(sid, sname)
                    self.state.set_session_state(sid, "connected")
                    payload = recv_exact(conn, blen) if blen > 0 else b""
                    self._on_chat_message(sid, sname, payload.decode("utf-8", errors="replace"), mid, rep)

                elif mtype == "FILE" and len(args) >= 4:
                    sid, sname, fname, fsize = args[0], args[1], args[2], int(args[3])
                    if fsize < 0:
                        raise ValueError(f"Invalid FILE size: {fsize}")
                    if not validate_peer_id(sid) or sid == my_pid or not validate_peer_name(sname):
                        raise ValueError(f"Invalid FILE sender identity '{sid[:24]}'")
                    if not self.state.get_peer_endpoint(sid):
                        raise ValueError(f"Rejected FILE from unknown peer '{sid[:12]}'")
                    mid = args[4] if len(args) >= 5 else ""
                    sha = args[5].lower() if len(args) >= 6 else ""
                    self.state.remember_peer_name(sid, sname)
                    self._handle_receive_file(conn, sid, sname, fname, fsize, mid, sha)
                    break

                elif mtype == "SEEN" and len(args) >= 2:
                    bind_chat(args[0])
                    if self.state.mark_outgoing_seen(args[0], args[1]):
                        self.ui.show_message(f"[*] {self.state.get_peer_name(args[0])} [#{args[0][:4]}] saw your messages.")

                elif mtype == "REACT" and len(args) >= 4:
                    sid, sname, mid, emoji = args[:4]
                    bind_chat(sid, sname)
                    if self.state.toggle_reaction(sid, mid, sid, sname, emoji):
                        self.ui.show_message(f"[*] {sname} [#{sid[:4]}] reacted {emoji} to a message.")

                elif mtype == "TYPING" and len(args) >= 2:
                    bind_chat(args[0])
                    self.state.set_peer_typing(args[0], args[1] == "1")

                elif mtype == "RECALL" and len(args) >= 2:
                    bind_chat(args[0])
                    if self.state.recall_message(args[0], args[1], requester_id=args[0]):
                        self.ui.show_message(f"[*] {self.state.get_peer_name(args[0])} [#{args[0][:4]}] recalled a message.")

                elif mtype == "CONNECT" and len(args) >= 1:
                    sid = args[0]
                    sname = args[1] if len(args) >= 2 and args[1] else self.state.get_peer_name(sid)
                    pport = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 0
                    bind_chat(sid, sname, peer_port=pport, allow_new_endpoint=True)
                    my_id, my_name, my_port, my_status = self.state.get_my_info()
                    _, lk = self._get_chat_socket_and_lock(sid)
                    ack_frame = encode_connect_ack_frame(my_id, my_name, my_port, my_status)
                    if lk:
                        with lk:
                            self._sendall_with_timeout(conn, ack_frame)
                    else:
                        self._sendall_with_timeout(conn, ack_frame)
                    if self.state.set_session_state(sid, "connected") == "disconnected":
                        label = f"{sname} reconnected"
                        self.state.record_divider(sid, label, tone="ok")
                        self.ui.show_message(f"──────── {label} [#{sid[:4]}] ────────")
                    else:
                        self.ui.show_message(f"[*] {sname} [#{sid[:4]}] connected TCP session.")

                elif mtype == "CONNECT_ACK" and len(args) >= 1:
                    sid = args[0]
                    sname = args[1] if len(args) >= 2 and args[1] else self.state.get_peer_name(sid)
                    pport = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 0
                    bind_chat(sid, sname, peer_port=pport, allow_new_endpoint=True)
                    if len(args) >= 4 and args[3] in ("online", "away"):
                        self.state.set_peer_status(sid, args[3])

                elif mtype == "STATUS" and len(args) >= 2:
                    sid, st_val = args[0], args[1]
                    bind_chat(sid)
                    if self.state.set_peer_status(sid, st_val):
                        self.ui.show_message(f"[*] {self.state.get_peer_name(sid)} [#{sid[:4]}] is now {st_val}.")

                elif mtype == "PING" and len(args) >= 1:
                    bind_chat(args[0])
                    self._enqueue("PONG", args[0])

                elif mtype == "PONG" and len(args) >= 1:
                    bind_chat(args[0])

                elif mtype == "BYE":
                    sid = args[0] if args else peer_id
                    if sid and len(args) >= 2 and args[1]:
                        self.state.remember_peer_name(sid, args[1])
                    reason = args[2].lower() if len(args) >= 3 and args[2] else ""
                    if sid:
                        if reason == "quit":
                            self.state.mark_peer_offline(sid, clear_endpoint=True)
                        self._handle_peer_disconnect(sid, conn)
                    break

                else:
                    self.ui.show_message(f"[!] Invalid protocol packet from {addr[0]}:{addr[1]} ('{header[:40]}') — connection closed.")
                    break

        except (ConnectionError, ValueError, UnicodeDecodeError, OSError) as exc:
            if not self._stop_event.is_set() and self.state.is_running():
                if is_chat_conn and peer_id:
                    self._handle_peer_disconnect(peer_id, conn)
                elif not is_chat_conn:
                    self.ui.show_message(f"[!] Malformed or closed connection from {addr[0]}:{addr[1]} ({exc}).")
        finally:
            if is_chat_conn and peer_id:
                self._unregister_chat_socket(peer_id, conn)
            self._safe_close(conn)

    def _on_chat_message(self, sid: str, sname: str, text: str, msg_id: str, reply_to: str) -> None:
        formatted = f"[{sname}#{sid[:4]}] {text}"
        is_active, unread, saved_id = self.state.record_incoming_message(
            sid, sname, formatted, raw_text=text, msg_id=msg_id or None, reply_to=reply_to
        )
        if is_active:
            self.ui.show_message(formatted)
            if self.state.is_ui_connected():
                self.notify_seen(sid, saved_id)
        else:
            self.ui.show_message(f"[*] New message from {sname} [#{sid[:4]}] ({unread} unread)")

    def _emit_disconnect(self, peer_id: str) -> None:
        if self.state.set_session_state(peer_id, "disconnected") != "disconnected":
            pname = self.state.get_peer_name(peer_id)
            self.state.record_divider(peer_id, f"{pname} disconnected", tone="danger")
            self.ui.show_message(f"──────── {pname} [#{peer_id[:4]}] disconnected ────────")

    def _handle_peer_disconnect(self, peer_id: str, conn: socket.socket) -> None:
        if self._unregister_chat_socket(peer_id, conn):
            self._emit_disconnect(peer_id)

    def _dial_chat_socket(
        self, partner_id: str, send_connect: bool = False, silent: bool = False, use_cached_endpoint: bool = False
    ) -> Tuple[Optional[socket.socket], Optional[threading.Lock], str, str]:
        peer_info = self.state.get_peer_endpoint(partner_id) if use_cached_endpoint else self.state.get_peer_by_id(partner_id)
        if not peer_info:
            err = f"{self.state.get_peer_name(partner_id)} hiện đang ngoại tuyến."
            if not silent:
                self.ui.show_message(f"[!] {err}")
            return None, None, err, ""

        ip, port, pname = peer_info["ip"], peer_info["port"], peer_info["name"]
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((ip, port))
            self._enable_keepalive(sock)
            if send_connect:
                my_pid, my_name, my_tcp_port, _ = self.state.get_my_info()
                sock.sendall(encode_connect_frame(my_pid, my_name, my_tcp_port))
                ack_line = recv_line(sock)
                ack_type, ack_args = parse_header(ack_line)
                if ack_type != "CONNECT_ACK" or not ack_args:
                    raise ConnectionError(f"Unexpected handshake response: {ack_type}")
                remote_pid = ack_args[0]
                remote_name = ack_args[1] if len(ack_args) >= 2 and ack_args[1] else remote_pid[:4]
                if remote_pid != partner_id:
                    self._safe_close(sock)
                    sock = None
                    self.state.mark_peer_offline(partner_id, clear_endpoint=True)
                    err = (
                        f"{pname} [#{partner_id[:4]}] đã thoát ứng dụng "
                        f"({ip}:{port} hiện thuộc về {remote_name} [#{remote_pid[:4]}])."
                    )
                    if not silent:
                        self.ui.show_message(f"[!] {err}")
                    return None, None, err, ""
                pname = remote_name
                remote_status = ack_args[3] if len(ack_args) >= 4 and ack_args[3] in ("online", "away") else ""
            else:
                remote_status = ""
            sock.settimeout(None)
        except (socket.timeout, ConnectionRefusedError, ConnectionError, ValueError, OSError) as exc:
            if sock:
                self._safe_close(sock)
            if not self.state.get_peer_by_id(partner_id):
                self.state.clear_peer_endpoint(partner_id)
            err = f"Không thể kết nối tới {pname} [#{partner_id[:4]}] ({ip}:{port}) — thiết bị đã tắt app hoặc ngoại tuyến."
            if not silent:
                self.ui.show_message(f"[!] {err} ({exc})")
            return None, None, err, ""

        self.state.touch_peer(partner_id, name=pname, ip=ip, tcp_port=port)
        if remote_status:
            self.state.set_peer_status(partner_id, remote_status)
        self._register_chat_socket(partner_id, sock)
        prev = self.state.set_session_state(partner_id, "connected")
        threading.Thread(target=self._receiver_loop, args=(sock, (ip, port), partner_id), daemon=True).start()
        s, lk = self._get_chat_socket_and_lock(partner_id)
        return s, lk, "", prev

    def _send_frame_sync(
        self, partner_id: str, frame: bytes, auto_connect: bool = True, silent: bool = False
    ) -> Tuple[bool, str]:
        if self.state.is_session_disconnected(partner_id):
            err = f"Đã ngắt kết nối với {self.state.get_peer_name(partner_id)}. Hãy bấm Kết nối lại."
            if not silent:
                self.ui.show_message(f"[!] {err}")
            return False, err

        sock, lk = self._get_chat_socket_and_lock(partner_id)
        if not sock or not lk:
            if not auto_connect:
                return False, "No active connection"
            sock, lk, err, _ = self._dial_chat_socket(partner_id, send_connect=True, silent=silent, use_cached_endpoint=True)
            if not sock or not lk:
                return False, err

        try:
            with lk:
                if sock.fileno() < 0:
                    raise ConnectionError("Socket already closed")
                self._sendall_with_timeout(sock, frame)
            return True, ""
        except (OSError, ValueError) as exc:
            self._handle_peer_disconnect(partner_id, sock)
            self._safe_close(sock)
            return False, str(exc)

    def _enqueue(self, *item) -> bool:
        if self._stop_event.is_set() or not self.state.is_running():
            return False
        pid = item[1]
        with self._outbox_lock:
            q = self._peer_outboxes.get(pid)
            if q is None:
                q = queue.Queue()
                self._peer_outboxes[pid] = q
                t = threading.Thread(target=self._peer_sender_loop, args=(pid, q), name=f"tcp-sender-{pid[:4]}", daemon=True)
                self._peer_workers[pid] = t
                t.start()
            q.put(item)
        return True

    def broadcast_status_tcp(self, status: str) -> None:
        if status not in ("online", "away"):
            return
        with self._conn_lock:
            pids = list(self._chat_sockets.keys())
        for pid in pids:
            self._enqueue("STATUS", pid, status)

    def send_message(self, partner_id: str, text: str, msg_id: str = "", reply_to: str = "") -> bool:
        if not self._enqueue("MSG", partner_id, text, msg_id, reply_to):
            if msg_id:
                self.state.update_message_status(partner_id, msg_id, "failed", error="Service stopped")
            return False
        return True

    def notify_seen(self, partner_id: str, explicit_msg_id: Optional[str] = None) -> None:
        if self._stop_event.is_set() or not self.state.is_running():
            return
        if explicit_msg_id:
            with self.state.lock:
                if self.state.last_seen_sent.get(partner_id) == explicit_msg_id:
                    return
                self.state.last_seen_sent[partner_id] = explicit_msg_id
            mid = explicit_msg_id
        else:
            mid = self.state.get_latest_incoming_msg_id(partner_id)
        if mid:
            self._enqueue("SEEN", partner_id, mid)

    def send_reaction(self, partner_id: str, msg_id: str, emoji: str) -> None:
        self._enqueue("REACT", partner_id, msg_id, emoji)

    def send_typing(self, partner_id: str, is_typing: bool) -> None:
        self._enqueue("TYPING", partner_id, is_typing)

    def send_recall(self, partner_id: str, msg_id: str) -> None:
        self._enqueue("RECALL", partner_id, msg_id)

    def close_chat(self, partner_id: str) -> None:
        if self.state.set_session_state(partner_id, "disconnected") != "disconnected":
            self.state.record_divider(partner_id, "Bạn đã rời cuộc trò chuyện", tone="warn")
        self._enqueue("BYE", partner_id)

    def open_chat(self, partner_id: str) -> Tuple[bool, str]:
        if self._stop_event.is_set() or not self.state.is_running():
            return False, "Dịch vụ đang dừng."
        if self.state.is_session_disconnected(partner_id):
            return False, f"Phiên chat với {self.state.get_peer_name(partner_id)} đang ngắt kết nối. Hãy bấm Kết nối lại hoặc gõ /reconnect."
        if self._get_chat_socket_and_lock(partner_id)[0]:
            self.state.set_session_state(partner_id, "connected")
            return True, ""
        sock, _, err, _ = self._dial_chat_socket(partner_id, send_connect=True)
        if not sock:
            return False, err
        info = self.state.get_peer_by_id(partner_id) or {}
        self.ui.show_message(f"[*] Connected TCP to {info.get('name', partner_id[:4])} [#{partner_id[:4]}] ({info.get('ip')}:{info.get('port')}).")
        self.notify_seen(partner_id)
        return True, ""

    def reconnect(self, partner_id: str) -> Tuple[bool, str]:
        if self._stop_event.is_set() or not self.state.is_running():
            return False, "Dịch vụ đang dừng."
        if old := self._pop_chat_conn(partner_id):
            self._safe_close(old)
        sock, _, err, prev = self._dial_chat_socket(partner_id, send_connect=True, use_cached_endpoint=True)
        if not sock:
            return False, err
        pname = self.state.get_peer_name(partner_id)
        label = f"Đã kết nối lại với {pname}" if prev == "disconnected" else f"Đã kết nối với {pname}"
        self.state.record_divider(partner_id, label, tone="ok")
        self.ui.show_message(f"──────── {label} [#{partner_id[:4]}] ────────")
        self.notify_seen(partner_id)
        return True, ""

    def _close_chat_sync(self, partner_id: str) -> None:
        sock, lk = self._get_chat_socket_and_lock(partner_id)
        if not sock or not lk:
            return
        my_pid, my_name = self.state.get_my_info()[:2]
        try:
            with lk:
                if sock.fileno() >= 0:
                    self._sendall_with_timeout(sock, encode_bye_frame(my_pid, my_name), timeout=1.5)
        except (OSError, ValueError):
            pass
        finally:
            self._unregister_chat_socket(partner_id, sock)
            self._safe_close(sock)

    def drop_peer(self, peer_id: str) -> None:
        if sock := self._pop_chat_conn(peer_id):
            self._safe_close(sock)
            self._emit_disconnect(peer_id)

    def cancel_file_transfer(self, transfer_id: str) -> bool:
        with self._transfer_lock:
            ev, sock = self._transfer_cancels.get(transfer_id), self._transfer_sockets.get(transfer_id)
        if not ev:
            return False
        ev.set()
        if sock:
            self._safe_close(sock)
        return True

    def cancel_active_transfers(self, target: str = "") -> list:
        key = (target or "").strip().lower()
        with self._transfer_lock:
            items = list(self._transfer_meta.items())
        cancelled = []
        for tid, meta in items:
            d, fn = meta.get("direction", ""), (meta.get("filename") or "").lower()
            match = (
                (not key or key == "all")
                or (key in ("send", "out", "gui") and d == "out")
                or (key in ("recv", "in", "nhan") and d == "in")
                or tid.lower().startswith(key.lstrip("#"))
                or fn == key
            )
            if match and self.cancel_file_transfer(tid):
                cancelled.append(dict(meta))
        return cancelled

    def get_active_transfers(self) -> list:
        with self._transfer_lock:
            return [dict(m) for m in self._transfer_meta.values()]

    def _register_transfer(self, tid: str, direction: str, filename: str, peer_name: str, file_size: int) -> threading.Event:
        ev = threading.Event()
        with self._transfer_lock:
            self._transfer_cancels[tid] = ev
            self._transfer_threads[tid] = threading.current_thread()
            self._transfer_meta[tid] = {
                "id": tid, "short_id": tid[:4], "direction": direction, "filename": filename,
                "peer_name": peer_name, "file_size": file_size, "transferred_bytes": 0, "progress": 0, "speed_str": "",
            }
        return ev

    def _update_transfer_meta(self, tid: str, done_bytes: int, pct: int, speed_str: str = "") -> None:
        with self._transfer_lock:
            if (m := self._transfer_meta.get(tid)) is not None:
                m["transferred_bytes"], m["progress"] = done_bytes, pct
                if speed_str:
                    m["speed_str"] = speed_str

    def _unregister_transfer(self, tid: str) -> None:
        with self._transfer_lock:
            for d in (self._transfer_cancels, self._transfer_sockets, self._transfer_meta, self._transfer_threads):
                d.pop(tid, None)

    def _make_progress_tracker(
        self, peer_id: str, tid: str, tag: str, filename: str, file_size: int, emit_cli: bool, min_interval: float
    ):
        start_t = time.time()
        step = 10 if file_size >= 128 * 1024 else 25
        st = {"pct": -1, "t": 0.0, "touch": start_t, "next_ms": step}

        def report(done_bytes: int) -> None:
            if file_size <= 0:
                return
            pct, now = int((done_bytes * 100) / file_size), time.time()
            if (now - st["touch"]) >= 2.0:
                self.state.touch_peer(peer_id)
                self._mark_tcp_rx(peer_id)
                st["touch"] = now
            spd = self._format_speed(done_bytes / max(now - start_t, 0.001))
            if pct - st["pct"] >= 1 or (now - st["t"]) >= min_interval:
                self._update_transfer_meta(tid, done_bytes, min(pct, 99), spd)
                self.state.update_file_progress(peer_id, tid, min(pct, 99), transferred_bytes=done_bytes, speed_str=spd)
                st["pct"], st["t"] = pct, now
            if emit_cli and pct >= st["next_ms"] and st["next_ms"] < 100:
                shown = min(pct, 99)
                self.ui.show_message(f"[*] [{tag} #{tid[:4]}] {filename}  {self._format_progress_bar(shown)} {shown:3d}%  {self._format_size_pair(done_bytes, file_size)}  ({spd})")
                while st["next_ms"] <= pct:
                    st["next_ms"] += step

        return start_t, report

    def _send_file_stream(
        self, partner_id: str, raw_filename: str, file_size: int, reader,
        upload_id: str = "", replace_msg_id: str = "", precomputed_sha256: str = "",
        source_path: str = "", emit_cli_bars: bool = False,
    ) -> Tuple[bool, str, str]:
        if self._stop_event.is_set() or not self.state.is_running():
            return False, "Dịch vụ đang dừng.", ""
        if self.state.is_session_disconnected(partner_id):
            return False, "Phiên chat đang ngắt kết nối. Hãy bấm Kết nối lại.", ""
        peer_info = self.state.get_peer_endpoint(partner_id)
        if not peer_info:
            return False, f"{self.state.get_peer_name(partner_id)} đang ngoại tuyến.", ""

        my_pid, my_name = self.state.get_my_info()[:2]
        pname, ip, port = peer_info["name"], peer_info["ip"], peer_info["port"]
        filename = sanitize_filename(raw_filename)
        is_img = is_image_filename(filename)

        mid = upload_id.strip() if upload_id and upload_id.strip() else self.state.new_msg_id()
        reused = self.state.reset_file_message_for_retry(partner_id, replace_msg_id, mid, filename, file_size) if replace_msg_id else None
        tid = mid if reused is not None else self.state.add_file_message(
            partner_id, "out", my_pid, my_name, filename, file_size, is_img,
            progress=0, transfer_status="transferring", msg_id=mid, sha256=precomputed_sha256, source_path=source_path,
        )
        cancel_ev = self._register_transfer(tid, "out", filename, pname, file_size)

        sock = preview_f = preview_abs = preview_rel = None
        sent, hasher = 0, hashlib.sha256()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((ip, port))
            sock.settimeout(FILE_IO_TIMEOUT)
            with self._transfer_lock:
                if tid in self._transfer_cancels:
                    self._transfer_sockets[tid] = sock

            sock.sendall(encode_file_header(my_pid, my_name, filename, file_size, msg_id=mid, sha256_hex=precomputed_sha256))
            size_str = self._format_size(file_size)
            if emit_cli_bars:
                self.ui.show_message(f"[*] [SEND #{tid[:4]}] {filename} ({size_str}) -> {pname} [#{partner_id[:4]}] (gõ /cancel hoặc /cancel {tid[:4]} để hủy)")

            if is_img and file_size <= 25 * 1024 * 1024:
                try:
                    os.makedirs(self.sent_dir, exist_ok=True)
                    preview_abs = self._unique_path_in(self.sent_dir, filename)
                    preview_f = open(preview_abs, "wb")
                    preview_rel = os.path.relpath(preview_abs, self.download_dir).replace("\\", "/")
                except OSError:
                    preview_f = preview_abs = preview_rel = None

            self.state.touch_peer(partner_id, name=pname, ip=ip, tcp_port=port)
            self._mark_tcp_rx(partner_id)
            start_t, report_prog = self._make_progress_tracker(partner_id, tid, "SEND", filename, file_size, emit_cli_bars, 0.1)
            max_bps = self.max_file_speed_mb * 1024 * 1024 if self.max_file_speed_mb > 0 else 0.0
            chunk_sz = 65536 if (max_bps == 0 and not emit_cli_bars) else CHUNK_SIZE

            remaining = file_size
            while remaining > 0 and not self._stop_event.is_set() and self.state.is_running() and not cancel_ev.is_set():
                chunk = reader.read(min(chunk_sz, remaining))
                if not chunk:
                    raise InterruptedError("Đã hủy gửi")
                sock.sendall(chunk)
                hasher.update(chunk)
                if preview_f:
                    try:
                        preview_f.write(chunk)
                    except OSError:
                        pass
                sent += len(chunk)
                remaining -= len(chunk)
                if max_bps > 0 and (wait := sent / max_bps - (time.time() - start_t)) > 0:
                    cancel_ev.wait(min(wait, 0.2))
                report_prog(sent)

            if cancel_ev.is_set() or sent != file_size:
                raise InterruptedError("Đã hủy gửi")

            if preview_f:
                preview_f.close()
                preview_f = None
            avg_spd = self._format_speed(file_size / max(time.time() - start_t, 0.001)) if file_size else "0 B/s"
            digest = precomputed_sha256 or hasher.hexdigest()
            self.state.update_file_progress(
                partner_id, tid, 100, transfer_status="done", file_path=preview_rel,
                transferred_bytes=file_size, speed_str=avg_spd, sha256=digest, sha256_verified=True,
            )
            if emit_cli_bars:
                done_msg = f"[*] [SEND #{tid[:4]}] {filename}  {self._format_progress_bar(100)} 100%  {self._format_size_pair(file_size, file_size)}  ({avg_spd}) — Done."
            else:
                done_msg = f"[*] Sent {filename} ({size_str}, {avg_spd}) to {pname} [#{partner_id[:4]}] — 100% Done."
            self.ui.show_message(done_msg)
            return True, "", tid

        except (InterruptedError, socket.timeout, ConnectionRefusedError, ConnectionError, BrokenPipeError, OSError) as exc:
            if preview_f:
                try:
                    preview_f.close()
                except OSError:
                    pass
                preview_f = None
            if preview_abs and os.path.exists(preview_abs):
                try:
                    os.remove(preview_abs)
                except OSError:
                    pass
            is_cancel = isinstance(exc, InterruptedError) or cancel_ev.is_set()
            err_text = "Đã hủy gửi" if is_cancel else self._friendly_transfer_error(exc)
            self.state.update_file_progress(
                partner_id, tid, int((sent * 100) / max(file_size, 1)),
                transfer_status="cancelled" if is_cancel else "failed", transferred_bytes=sent, error=err_text,
            )
            self.ui.show_message(
                f"[!] Cancelled sending {filename} to {pname}." if is_cancel
                else f"[!] File transfer stopped ({filename} -> {pname}): {err_text}"
            )
            return False, err_text, tid

        finally:
            self._unregister_transfer(tid)
            if preview_f:
                try:
                    preview_f.close()
                except OSError:
                    pass
            if sock:
                self._safe_close(sock)

    def stream_file_from_reader(
        self, partner_id: str, raw_filename: str, file_size: int, reader,
        upload_id: str = "", replace_msg_id: str = "", precomputed_sha256: str = "",
    ) -> Tuple[bool, str, str]:
        return self._send_file_stream(
            partner_id, raw_filename, file_size, reader,
            upload_id=upload_id, replace_msg_id=replace_msg_id, precomputed_sha256=precomputed_sha256,
        )

    def retry_file_transfer(self, partner_id: str, old_msg_id: str) -> Tuple[bool, str]:
        if self.state.is_session_disconnected(partner_id):
            return False, "Phiên chat đang ngắt kết nối. Hãy bấm Kết nối lại."
        if not self.state.get_peer_endpoint(partner_id):
            return False, f"{self.state.get_peer_name(partner_id)} đang ngoại tuyến."
        msg = self.state.get_file_message_by_id(partner_id, old_msg_id)
        src = (msg or {}).get("source_path") or ""
        if not msg or msg.get("direction") != "out" or not src or not os.path.isfile(src):
            return False, "Tệp gốc không còn tồn tại trên máy."
        ok = self.send_file_async(partner_id, src, display_name=msg.get("filename"), replace_msg_id=old_msg_id)
        return (True, "") if ok else (False, "Không thể khởi chạy gửi lại tệp.")

    def send_file_async(
        self, partner_id: str, filepath: str, display_name: Optional[str] = None,
        remove_source_after: bool = False, replace_msg_id: str = "",
    ) -> bool:
        if self.state.is_session_disconnected(partner_id):
            self.ui.show_message(f"[!] Đã ngắt kết nối với {self.state.get_peer_name(partner_id)}. Hãy bấm Kết nối lại trước khi gửi tệp.")
            return False
        if not self.state.get_peer_endpoint(partner_id):
            self.ui.show_message(f"[!] {self.state.get_peer_name(partner_id)} is offline. Cannot send file.")
            return False

        def worker():
            try:
                fsize = os.path.getsize(filepath)
                sha = compute_file_sha256(filepath)
                with open(filepath, "rb") as f:
                    self._send_file_stream(
                        partner_id, display_name or filepath, fsize, f,
                        replace_msg_id=replace_msg_id, precomputed_sha256=sha,
                        source_path="" if remove_source_after else os.path.abspath(filepath),
                        emit_cli_bars=not bool(getattr(self.ui, "is_web_ui", False)),
                    )
            except OSError as exc:
                self.ui.show_message(f"[!] Cannot read file '{os.path.basename(filepath)}': {exc}")
            finally:
                if remove_source_after and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

        threading.Thread(target=worker, name=f"file-sender-{os.path.basename(filepath)}", daemon=True).start()
        return True

    def _handle_receive_file(
        self, conn: socket.socket, sender_id: str, sender_name: str,
        raw_filename: str, file_size: int, msg_id: str = "", expected_sha256: str = "",
    ) -> None:
        safe_name = sanitize_filename(raw_filename)
        dest_path = self._unique_path_in(self.download_dir, safe_name)
        part_path = dest_path + ".part"
        size_str = self._format_size(file_size)
        is_web = bool(getattr(self.ui, "is_web_ui", False))

        tid = self.state.add_file_message(
            sender_id, "in", sender_id, sender_name, safe_name, file_size,
            is_image_filename(safe_name), progress=0, transfer_status="transferring",
            msg_id=msg_id or None, sha256=expected_sha256,
        )
        cancel_ev = self._register_transfer(tid, "in", safe_name, sender_name, file_size)
        with self._transfer_lock:
            if tid in self._transfer_cancels:
                self._transfer_sockets[tid] = conn
        if not is_web:
            self.ui.show_message(f"[*] [RECV #{tid[:4]}] {safe_name} ({size_str}) <- {sender_name} [#{sender_id[:4]}] (gõ /cancel hoặc /cancel {tid[:4]} để hủy)")

        received, hasher = 0, hashlib.sha256()
        self.state.touch_peer(sender_id, name=sender_name)
        self._mark_tcp_rx(sender_id)
        start_t, report_prog = self._make_progress_tracker(sender_id, tid, "RECV", safe_name, file_size, not is_web, 0.08)

        try:
            conn.settimeout(FILE_IO_TIMEOUT)
            with open(part_path, "wb") as f:
                while received < file_size:
                    if cancel_ev.is_set() or self._stop_event.is_set() or not self.state.is_running():
                        raise InterruptedError("Đã hủy nhận")
                    chunk = conn.recv(min(CHUNK_SIZE, file_size - received))
                    if not chunk:
                        raise ConnectionError("Sender disconnected before transfer completed")
                    f.write(chunk)
                    hasher.update(chunk)
                    received += len(chunk)
                    report_prog(received)

            actual_sha = hasher.hexdigest()
            avg_spd = self._format_speed(file_size / max(time.time() - start_t, 0.001)) if file_size else "0 B/s"
            if expected_sha256 and actual_sha != expected_sha256:
                if os.path.exists(part_path):
                    os.remove(part_path)
                self.state.update_file_progress(
                    sender_id, tid, 100, transfer_status="failed", transferred_bytes=received,
                    speed_str=avg_spd, sha256=actual_sha, sha256_verified=False, error="Sai mã băm SHA-256 (file bị hỏng)",
                )
                self.ui.show_message(f"[!] SHA-256 mismatch for {safe_name} from {sender_name} [#{sender_id[:4]}]. Partial file deleted.")
                return

            os.replace(part_path, dest_path)
            rel_path = os.path.relpath(dest_path, self.download_dir).replace("\\", "/")
            self.state.update_file_progress(
                sender_id, tid, 100, transfer_status="done", file_path=rel_path,
                transferred_bytes=file_size, speed_str=avg_spd, sha256=actual_sha,
                sha256_verified=(True if expected_sha256 else None),
            )
            if is_web:
                msg_done = f"[*] File received from {sender_name} [#{sender_id[:4]}]: downloads/{rel_path} ({size_str}, {avg_spd})"
            else:
                msg_done = f"[*] [RECV #{tid[:4]}] {safe_name}  {self._format_progress_bar(100)} 100%  {self._format_size_pair(file_size, file_size)}  ({avg_spd}) -> downloads/{rel_path}"
            self.ui.show_message(msg_done)
            if self.state.get_current_partner() == sender_id and self.state.is_ui_connected():
                self.notify_seen(sender_id, tid)

        except (InterruptedError, socket.timeout, OSError, ConnectionError) as exc:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            is_cancel = cancel_ev.is_set() or isinstance(exc, InterruptedError)
            self.state.update_file_progress(
                sender_id, tid, int((received * 100) / max(file_size, 1)),
                transfer_status="cancelled" if is_cancel else "failed", transferred_bytes=received,
                error="Đã hủy nhận" if is_cancel else "Người gửi đã hủy hoặc mất kết nối",
            )
            self.ui.show_message(f"[!] File receive {'cancelled' if is_cancel else 'interrupted'} ({safe_name} from {sender_name}): {exc}. Partial file deleted.")
        finally:
            self._unregister_transfer(tid)

    def _register_chat_socket(self, peer_id: str, sock: socket.socket) -> None:
        now = time.time()
        with self._conn_lock:
            old = self._chat_sockets.get(peer_id)
            if old and old is not sock:
                self._safe_close(old)
            self._chat_sockets[peer_id] = sock
            self._send_locks[peer_id] = threading.Lock()
            self._last_tcp_rx[peer_id] = now
            self._last_ping_sent[peer_id] = now

    def _mark_tcp_rx(self, peer_id: str) -> None:
        with self._conn_lock:
            if peer_id in self._chat_sockets:
                self._last_tcp_rx[peer_id] = time.time()

    def _pop_chat_conn(self, peer_id: str, expected: Optional[socket.socket] = None) -> Optional[socket.socket]:
        with self._conn_lock:
            sock = self._chat_sockets.get(peer_id)
            if sock is None or (expected is not None and sock is not expected):
                return None
            for d in (self._chat_sockets, self._send_locks, self._last_tcp_rx, self._last_ping_sent):
                d.pop(peer_id, None)
            return sock

    def _unregister_chat_socket(self, peer_id: str, sock: socket.socket) -> bool:
        return self._pop_chat_conn(peer_id, expected=sock) is not None

    @staticmethod
    def _sendall_with_timeout(sock: socket.socket, data: bytes, timeout: float = SEND_TIMEOUT) -> None:
        view = memoryview(data)
        total, sent = len(view), 0
        while sent < total:
            if sock.fileno() < 0:
                raise ConnectionError("Socket already closed")
            try:
                _, writable, _ = select.select([], [sock], [], timeout)
            except ValueError as exc:
                raise ConnectionError("Socket closed while waiting to send") from exc
            if not writable:
                raise socket.timeout("Send buffer blocked (peer unreachable)")
            n = sock.send(view[sent:sent + CHUNK_SIZE])
            if n <= 0:
                raise ConnectionError("Socket closed while sending")
            sent += n

    @staticmethod
    def _enable_keepalive(sock: socket.socket) -> None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass

    def _get_chat_socket_and_lock(self, peer_id: str) -> Tuple[Optional[socket.socket], Optional[threading.Lock]]:
        with self._conn_lock:
            return self._chat_sockets.get(peer_id), self._send_locks.get(peer_id)

    @staticmethod
    def _unique_path_in(directory: str, filename: str) -> str:
        base = os.path.join(directory, filename)
        if not os.path.exists(base):
            return base
        stem, ext = os.path.splitext(filename)
        i = 1
        while os.path.exists(cand := os.path.join(directory, f"{stem}({i}){ext}")):
            i += 1
        return cand

    @staticmethod
    def _format_progress_bar(percent: int, width: int = 20) -> str:
        filled = int((max(0, min(100, int(percent))) * width) // 100)
        ch_on, ch_off = ("█", "░") if "utf" in (getattr(sys.stdout, "encoding", None) or "").lower() else ("#", "-")
        return f"[{ch_on * filled}{ch_off * (width - filled)}]"

    @staticmethod
    def _format_size_pair(done_bytes: int, total_bytes: int) -> str:
        total, done = max(float(total_bytes), 0.0), max(0.0, min(float(done_bytes), max(float(total_bytes), float(done_bytes))))
        units, div, u = ("B", "KB", "MB", "GB"), 1.0, 0
        while total / div >= 1024.0 and u < 3:
            div *= 1024.0
            u += 1
        return f"{int(done)} / {int(total)} B" if u == 0 else f"{done / div:.2f} / {total / div:.2f} {units[u]}"

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        s = float(num_bytes)
        for u in ("B", "KB", "MB", "GB"):
            if s < 1024 or u == "GB":
                return f"{int(s)} B" if u == "B" else f"{s:.1f} {u}"
            s /= 1024
        return f"{s:.1f} GB"

    @staticmethod
    def _format_speed(bps: float) -> str:
        return TCPService._format_size(int(max(bps, 0.0))) + "/s"

    @staticmethod
    def _friendly_transfer_error(exc: Exception) -> str:
        if isinstance(exc, socket.timeout):
            return "Hết thời gian chờ (mất kết nối mạng)"
        if isinstance(exc, ConnectionRefusedError):
            return "Không thể kết nối tới đối phương"
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)) or getattr(exc, "winerror", None) in (10053, 10054) or getattr(exc, "errno", None) in (32, 104):
            return "Người nhận đã hủy hoặc mất kết nối"
        return str(exc)

    @staticmethod
    def _safe_close(sock: socket.socket) -> None:
        for fn in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
            try:
                fn()
            except OSError:
                pass
