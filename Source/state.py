import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from protocol import generate_peer_id

class AppState:
    def __init__(
        self, name: str, tcp_port: int, udp_port: int = 9999, room: str = "default", peer_id: Optional[str] = None
    ):
        self.lock = threading.Lock()
        self._cond = threading.Condition(self.lock)
        self._version: int = 0

        self.my_peer_id: str = peer_id or generate_peer_id()
        self.my_name: str = name
        self.my_tcp_port: int = tcp_port
        self.my_udp_port: int = udp_port
        self.my_room: str = room
        self.my_status: str = "online"
        self.running: bool = True
        self.ui_connected: bool = True

        self.online_peers: Dict[str, dict] = {}
        self.peer_endpoints: Dict[str, Tuple[str, int]] = {}
        self.peer_names: Dict[str, str] = {self.my_peer_id: self.my_name}
        self.current_partner: Optional[str] = None
        self.last_partner: Optional[str] = None

        self.messages: Dict[str, List[dict]] = {}
        self.terminal_entries: List[dict] = []
        self.unread_counts: Dict[str, int] = {}
        self.last_seen_sent: Dict[str, str] = {}
        self.typing_peers: Dict[str, float] = {}
        self.session_states: Dict[str, str] = {}

    def _notify_locked(self) -> None:
        self._version += 1
        self._cond.notify_all()

    def get_version(self) -> int:
        with self.lock:
            return self._version

    def wait_for_change(self, last_version: int, timeout: float = 15.0) -> int:
        with self._cond:
            if self._version == last_version and self.running:
                self._cond.wait(timeout=timeout)
            return self._version

    @staticmethod
    def _now_str() -> str:
        return time.strftime("%H:%M")

    @staticmethod
    def _now_full_str() -> str:
        return time.strftime("%H:%M:%S")

    @staticmethod
    def new_msg_id() -> str:
        return uuid.uuid4().hex[:12]

    def stop(self) -> None:
        with self.lock:
            self.running = False
            self._notify_locked()

    def is_running(self) -> bool:
        with self.lock:
            return self.running

    def set_ui_connected(self, connected: bool) -> None:
        with self.lock:
            self.ui_connected = connected

    def is_ui_connected(self) -> bool:
        with self.lock:
            return self.ui_connected

    def set_status(self, status: str) -> None:
        with self.lock:
            if self.my_status != status:
                self.my_status = status
                self._notify_locked()

    def get_my_info(self) -> Tuple[str, str, int, str]:
        with self.lock:
            return self.my_peer_id, self.my_name, self.my_tcp_port, self.my_status

    @staticmethod
    def _classify_log_channel(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ("udp", "joined room", "is now ", "timeout", "broadcast")):
            return "udp"
        if any(k in t for k in ("tcp", "file", "sending", "receiving", "saw your", "reacted", "recalled", "disconnected", "reconnected", "connection", "invalid protocol", "malformed")):
            return "tcp"
        return "sys"

    def _append_terminal_locked(self, kind: str, channel: str, command: str, text: str) -> None:
        self.terminal_entries.append({
            "id": self.new_msg_id(),
            "time": self._now_full_str(),
            "kind": kind,
            "channel": channel,
            "command": command,
            "text": text,
        })
        if len(self.terminal_entries) > 400:
            self.terminal_entries = self.terminal_entries[-400:]
        self._notify_locked()

    def add_log(self, text: str) -> None:
        with self.lock:
            self._append_terminal_locked("log", self._classify_log_channel(text), "", text)

    def record_terminal_command(self, command_line: str, output_text: str, is_error: bool = False) -> None:
        with self.lock:
            self._append_terminal_locked("cmd_err" if is_error else "cmd_ok", "cmd", command_line, output_text)

    def clear_terminal(self) -> None:
        with self.lock:
            self.terminal_entries.clear()
            self._notify_locked()

    def remember_peer_name(self, peer_id: str, name: str) -> None:
        if peer_id and name:
            with self.lock:
                self.peer_names[peer_id] = name

    def _get_peer_name_locked(self, peer_id: str) -> str:
        if peer_id == self.my_peer_id:
            return self.my_name
        info = self.online_peers.get(peer_id)
        return (info.get("name") if info else None) or self.peer_names.get(peer_id, peer_id[:4])

    def get_peer_name(self, peer_id: str) -> str:
        with self.lock:
            return self._get_peer_name_locked(peer_id)

    def format_peer_label(self, peer_id: str) -> str:
        with self.lock:
            name = self._get_peer_name_locked(peer_id)
            same = sum(1 for info in self.online_peers.values() if info.get("name") == name)
            return f"{name}#{peer_id[:4]}" if (name == self.my_name or same > 1) else name

    def update_peer(self, peer_id: str, name: str, ip: str, tcp_port: int, status: str) -> Tuple[bool, Optional[str]]:
        with self.lock:
            old = self.online_peers.get(peer_id)
            is_new = old is None
            status_changed = status if (old and old["status"] != status) else None
            changed = is_new or bool(status_changed) or (old["ip"], old["port"], old["name"]) != (ip, tcp_port, name)
            self.peer_names[peer_id] = name
            if ip and tcp_port > 0:
                if self._claim_endpoint_locked(peer_id, ip, tcp_port):
                    changed = True
            self.online_peers[peer_id] = {
                "peer_id": peer_id, "name": name, "ip": ip, "port": tcp_port, "status": status, "last_seen": time.time(),
            }
            if changed:
                self._notify_locked()
            return is_new, status_changed

    def _claim_endpoint_locked(self, peer_id: str, ip: str, tcp_port: int) -> bool:
        self.peer_endpoints[peer_id] = (ip, tcp_port)
        evicted = False
        for other_id, ep in list(self.peer_endpoints.items()):
            if other_id != peer_id and ep == (ip, tcp_port):
                del self.peer_endpoints[other_id]
                evicted = True
        for other_id, info in list(self.online_peers.items()):
            if other_id != peer_id and (info.get("ip"), info.get("port")) == (ip, tcp_port):
                del self.online_peers[other_id]
                self.typing_peers.pop(other_id, None)
                evicted = True
        return evicted

    def clear_peer_endpoint(self, peer_id: str) -> None:
        with self.lock:
            changed = self.peer_endpoints.pop(peer_id, None) is not None
            if changed:
                self._notify_locked()

    def mark_peer_offline(self, peer_id: str, clear_endpoint: bool = True) -> bool:
        with self.lock:
            changed = False
            if peer_id in self.online_peers:
                del self.online_peers[peer_id]
                changed = True
            self.typing_peers.pop(peer_id, None)
            if clear_endpoint and peer_id in self.peer_endpoints:
                del self.peer_endpoints[peer_id]
                changed = True
            if changed:
                self._notify_locked()
            return changed

    def touch_peer(self, peer_id: str, name: str = "", ip: str = "", tcp_port: int = 0) -> bool:
        if not peer_id or peer_id == self.my_peer_id:
            return False
        now = time.time()
        with self.lock:
            if name:
                self.peer_names[peer_id] = name
            cached = self.peer_endpoints.get(peer_id)
            eff_ip = ip or (cached[0] if cached else "")
            eff_port = tcp_port if tcp_port > 0 else (cached[1] if cached else 0)
            if eff_ip and eff_port > 0:
                self._claim_endpoint_locked(peer_id, eff_ip, eff_port)

            cur = self.online_peers.get(peer_id)
            if cur is not None:
                cur["last_seen"] = now
                updates = {k: v for k, v in (("name", name), ("ip", eff_ip), ("port", eff_port or None)) if v and cur[k] != v}
                if updates:
                    cur.update(updates)
                    self._notify_locked()
                return True

            if eff_ip and eff_port > 0:
                self.online_peers[peer_id] = {
                    "peer_id": peer_id,
                    "name": name or self._get_peer_name_locked(peer_id),
                    "ip": eff_ip,
                    "port": eff_port,
                    "status": "online",
                    "last_seen": now,
                }
                self._notify_locked()
                return True
            return False

    def set_peer_status(self, peer_id: str, status: str) -> Optional[str]:
        if status not in ("online", "away"):
            return None
        with self.lock:
            info = self.online_peers.get(peer_id)
            if not info or info.get("status") == status:
                return None
            info["status"] = status
            info["last_seen"] = time.time()
            self._notify_locked()
            return status

    def delete_conversation(self, peer_id: str) -> bool:
        if not peer_id:
            return False
        with self.lock:
            had_data = (
                peer_id in self.messages
                or peer_id in self.unread_counts
                or (peer_id not in self.online_peers and (peer_id in self.session_states or peer_id in self.peer_endpoints))
            )
            self.messages.pop(peer_id, None)
            self.unread_counts.pop(peer_id, None)
            self.last_seen_sent.pop(peer_id, None)
            if peer_id not in self.online_peers:
                self.session_states.pop(peer_id, None)
                self.peer_endpoints.pop(peer_id, None)
                self.typing_peers.pop(peer_id, None)
                if self.current_partner == peer_id:
                    self.current_partner = None
                if self.last_partner == peer_id:
                    self.last_partner = None
            if had_data:
                self._notify_locked()
            return had_data

    def get_peer_endpoint(self, peer_id: str) -> Optional[dict]:
        with self.lock:
            info = self.online_peers.get(peer_id)
            if info:
                return dict(info)
            ep = self.peer_endpoints.get(peer_id)
            if ep:
                return {
                    "peer_id": peer_id,
                    "name": self._get_peer_name_locked(peer_id),
                    "ip": ep[0],
                    "port": ep[1],
                    "status": "offline",
                }
            return None

    def remove_expired_peers(self, timeout_sec: float = 10.0) -> List[Tuple[str, str, bool]]:
        now, expired = time.time(), []
        with self.lock:
            for pid, info in list(self.online_peers.items()):
                if now - info["last_seen"] > timeout_sec:
                    del self.online_peers[pid]
                    self.typing_peers.pop(pid, None)
                    expired.append((pid, info.get("name", pid[:4]), self.current_partner == pid))
            if expired:
                self._notify_locked()
        return expired

    def get_peer_list(self) -> List[Tuple[str, dict, int]]:
        with self.lock:
            return [(pid, dict(info), self.unread_counts.get(pid, 0)) for pid, info in self.online_peers.items()]

    def get_peer_by_id(self, peer_id: str) -> Optional[dict]:
        with self.lock:
            info = self.online_peers.get(peer_id)
            return dict(info) if info else None

    def get_peer_by_identifier(self, identifier: str) -> Tuple[Optional[str], Optional[dict], List[Tuple[str, dict]]]:
        with self.lock:
            if identifier in self.online_peers:
                return identifier, dict(self.online_peers[identifier]), []
            items = list(self.online_peers.items())
            if identifier.isdigit():
                idx = int(identifier) - 1
                return (items[idx][0], dict(items[idx][1]), []) if 0 <= idx < len(items) else (None, None, [])
            for predicate in (
                lambda pid, _: len(identifier) >= 4 and pid.startswith(identifier),
                lambda _, info: info.get("name") == identifier,
            ):
                matches = [(pid, dict(info)) for pid, info in items if predicate(pid, info)]
                if len(matches) == 1:
                    return matches[0][0], matches[0][1], []
                if len(matches) > 1:
                    return None, None, matches
            return None, None, []

    def _cli_history_locked(self, peer_id: str) -> List[str]:
        out = []
        for m in self.messages.get(peer_id, []):
            k = m.get("kind")
            if k == "divider":
                out.append(f"──── {m.get('text', '')} ────")
            elif k == "system":
                out.append(m.get("text", ""))
            elif k == "text":
                sid = (m.get("sender_id") or "")[:4]
                out.append(f"[{m.get('sender', '?')}#{sid}] {m.get('text', '')}")
            elif k in ("file", "image"):
                tag = "Sent" if m.get("direction") == "out" else "Recv"
                out.append(f"[*] {tag} {m.get('filename', 'file')} ({m.get('transfer_status', '')})")
        return out

    def set_current_partner(self, partner_id: Optional[str]) -> Tuple[int, List[str]]:
        with self.lock:
            self.current_partner = partner_id
            if partner_id:
                self.last_partner = partner_id
                unread = self.unread_counts.pop(partner_id, 0)
                history = self._cli_history_locked(partner_id)
                self._notify_locked()
                return unread, history
            self._notify_locked()
            return 0, []

    def get_current_partner(self) -> Optional[str]:
        with self.lock:
            return self.current_partner

    def get_last_partner(self) -> Optional[str]:
        with self.lock:
            return self.current_partner or self.last_partner

    def get_session_state(self, peer_id: str) -> str:
        with self.lock:
            return self.session_states.get(peer_id, "idle")

    def is_session_disconnected(self, peer_id: str) -> bool:
        with self.lock:
            return self.session_states.get(peer_id) == "disconnected"

    def set_session_state(self, peer_id: str, state_name: str) -> str:
        with self.lock:
            prev = self.session_states.get(peer_id, "idle")
            if state_name == "disconnected":
                self.typing_peers.pop(peer_id, None)
            if prev != state_name:
                self.session_states[peer_id] = state_name
                self._notify_locked()
            return prev

    def _find_msg_locked(self, peer_id: str, msg_id: str) -> Optional[dict]:
        for m in reversed(self.messages.get(peer_id, [])):
            if m.get("id") == msg_id or m.get("transfer_id") == msg_id:
                return m
        return None

    def _build_reply_preview_locked(self, peer_id: str, reply_to_id: str) -> Optional[dict]:
        if not reply_to_id:
            return None
        m = self._find_msg_locked(peer_id, reply_to_id)
        if not m:
            return {"id": reply_to_id, "sender_id": "", "sender": "", "text": "Tin nhắn gốc"}
        if m.get("recalled"):
            snippet = "Tin nhắn đã được thu hồi"
        elif m.get("kind") == "image":
            snippet = f"📷 {m.get('filename', 'Ảnh')}"
        elif m.get("kind") == "file":
            snippet = f"📎 {m.get('filename', 'Tệp')}"
        else:
            snippet = m.get("text", "")[:70]
        return {"id": reply_to_id, "sender_id": m.get("sender_id", ""), "sender": m.get("sender", ""), "text": snippet}

    def record_incoming_message(
        self, sender_id: str, sender_name: str, formatted_line: str,
        raw_text: Optional[str] = None, msg_id: Optional[str] = None, reply_to: str = "",
    ) -> Tuple[bool, int, str]:
        mid = msg_id or self.new_msg_id()
        with self.lock:
            if sender_name:
                self.peer_names[sender_id] = sender_name
            self.typing_peers.pop(sender_id, None)
            self.messages.setdefault(sender_id, []).append({
                "id": mid, "kind": "text", "direction": "in",
                "sender_id": sender_id, "sender": sender_name or self._get_peer_name_locked(sender_id),
                "text": formatted_line if raw_text is None else raw_text,
                "timestamp": self._now_str(), "status": "received", "error": "",
                "reactions": {}, "reply_to": self._build_reply_preview_locked(sender_id, reply_to), "recalled": False,
            })
            if self.current_partner == sender_id:
                self._notify_locked()
                return True, 0, mid
            self.unread_counts[sender_id] = self.unread_counts.get(sender_id, 0) + 1
            self._notify_locked()
            return False, self.unread_counts[sender_id], mid

    def record_outgoing_message(
        self, partner_id: str, formatted_line: str,
        raw_text: Optional[str] = None, msg_id: Optional[str] = None, reply_to: str = "",
    ) -> str:
        mid = msg_id or self.new_msg_id()
        with self.lock:
            self.messages.setdefault(partner_id, []).append({
                "id": mid, "kind": "text", "direction": "out",
                "sender_id": self.my_peer_id, "sender": self.my_name,
                "text": formatted_line if raw_text is None else raw_text,
                "timestamp": self._now_str(), "status": "sending", "error": "", "seen_at": "",
                "reactions": {}, "reply_to": self._build_reply_preview_locked(partner_id, reply_to), "recalled": False,
            })
            self._notify_locked()
        return mid

    def update_message_status(self, peer_id: str, msg_id: str, status: str, error: str = "") -> bool:
        with self.lock:
            m = self._find_msg_locked(peer_id, msg_id)
            if not m or m.get("direction") != "out" or (m.get("status") == "seen" and status == "sent"):
                return False
            m["status"], m["error"] = status, error
            self._notify_locked()
            return True

    def prepare_message_retry(self, peer_id: str, msg_id: str) -> Optional[Tuple[str, str]]:
        with self.lock:
            m = self._find_msg_locked(peer_id, msg_id)
            if not m or m.get("direction") != "out" or m.get("kind") != "text" or m.get("recalled") or m.get("status") != "failed":
                return None
            m.update({"status": "sending", "error": "", "timestamp": self._now_str()})
            rep = m.get("reply_to")
            self._notify_locked()
            return m.get("text", ""), (rep.get("id", "") if isinstance(rep, dict) else "")

    def record_divider(self, peer_id: str, label: str, tone: str = "danger") -> None:
        with self.lock:
            self.messages.setdefault(peer_id, []).append({
                "id": self.new_msg_id(), "kind": "divider", "direction": "sys",
                "sender_id": "system", "sender": "system", "text": label, "tone": tone, "timestamp": self._now_str(),
            })
            self._notify_locked()

    def add_file_message(
        self, peer_id: str, direction: str, sender_id: str, sender_name: str,
        filename: str, file_size: int, is_image: bool, file_path: Optional[str] = None,
        progress: int = 0, transfer_status: str = "transferring", msg_id: Optional[str] = None,
        sha256: str = "", source_path: str = "",
    ) -> str:
        tid = msg_id or self.new_msg_id()
        with self.lock:
            if sender_id and sender_name:
                self.peer_names[sender_id] = sender_name
            self.messages.setdefault(peer_id, []).append({
                "id": tid, "transfer_id": tid, "kind": "image" if is_image else "file",
                "direction": direction, "sender_id": sender_id,
                "sender": sender_name or self._get_peer_name_locked(sender_id),
                "filename": filename, "file_size": file_size, "file_path": file_path,
                "source_path": source_path, "progress": progress, "transferred_bytes": 0,
                "speed_str": "", "sha256": sha256, "sha256_verified": None,
                "transfer_status": transfer_status, "status": "sending" if direction == "out" else "received",
                "seen_at": "", "reactions": {}, "reply_to": None, "recalled": False, "error": "",
                "timestamp": self._now_str(),
            })
            if direction == "in" and self.current_partner != peer_id:
                self.unread_counts[peer_id] = self.unread_counts.get(peer_id, 0) + 1
            self._notify_locked()
        return tid

    def update_file_progress(
        self, peer_id: str, transfer_id: str, progress: int,
        transfer_status: Optional[str] = None, file_path: Optional[str] = None,
        error: Optional[str] = None, speed_str: Optional[str] = None,
        sha256: Optional[str] = None, sha256_verified: Optional[bool] = None,
        transferred_bytes: Optional[int] = None,
    ) -> None:
        with self.lock:
            msg = self._find_msg_locked(peer_id, transfer_id)
            if not msg:
                return
            msg["progress"] = progress
            for k, v in (
                ("transferred_bytes", transferred_bytes), ("file_path", file_path), ("error", error),
                ("speed_str", speed_str), ("sha256", sha256), ("sha256_verified", sha256_verified),
            ):
                if v is not None:
                    msg[k] = v
            if transfer_status is not None:
                msg["transfer_status"] = transfer_status
                if msg.get("direction") == "out":
                    if transfer_status == "done" and msg.get("status") != "seen":
                        msg["status"] = "sent"
                    elif transfer_status in ("failed", "cancelled"):
                        msg["status"] = "failed"
            self._notify_locked()

    def reset_file_message_for_retry(
        self, peer_id: str, old_msg_id: str, new_msg_id: str,
        filename: Optional[str] = None, file_size: Optional[int] = None,
    ) -> Optional[dict]:
        with self.lock:
            msg = self._find_msg_locked(peer_id, old_msg_id)
            if not msg or msg.get("direction") != "out" or msg.get("kind") not in ("file", "image"):
                return None
            msg.update({
                "id": new_msg_id, "transfer_id": new_msg_id, "progress": 0, "transferred_bytes": 0,
                "speed_str": "", "transfer_status": "transferring", "status": "sending",
                "error": "", "sha256": "", "sha256_verified": None, "timestamp": self._now_str(),
            })
            if filename is not None:
                msg["filename"] = filename
            if file_size is not None:
                msg["file_size"] = file_size
            self._notify_locked()
            return dict(msg)

    def get_file_message_by_id(self, peer_id: str, msg_id: str) -> Optional[dict]:
        with self.lock:
            m = self._find_msg_locked(peer_id, msg_id)
            return dict(m) if (m and m.get("kind") in ("file", "image")) else None

    def get_latest_incoming_msg_id(self, peer_id: str) -> Optional[str]:
        with self.lock:
            for m in reversed(self.messages.get(peer_id, [])):
                if m.get("direction") == "in" and m.get("id"):
                    mid = m["id"]
                    if self.last_seen_sent.get(peer_id) == mid:
                        return None
                    self.last_seen_sent[peer_id] = mid
                    return mid
            return None

    def mark_outgoing_seen(self, peer_id: str, last_msg_id: str) -> bool:
        now_t = self._now_str()
        with self.lock:
            msgs = self.messages.get(peer_id, [])
            if not msgs:
                return False
            limit = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("id") == last_msg_id), len(msgs) - 1)
            changed = False
            for m in msgs[:limit + 1]:
                if m.get("direction") == "out" and m.get("status") not in ("seen", "failed"):
                    m["status"], m["seen_at"], changed = "seen", now_t, True
            if changed:
                self._notify_locked()
            return changed

    def toggle_reaction(self, peer_id: str, msg_id: str, reactor_id: str, reactor_name: str, emoji: str) -> bool:
        with self.lock:
            if reactor_id and reactor_name:
                self.peer_names[reactor_id] = reactor_name
            m = self._find_msg_locked(peer_id, msg_id)
            if not m or m.get("recalled"):
                return False
            users = m.setdefault("reactions", {}).setdefault(emoji, [])
            if reactor_id in users:
                users.remove(reactor_id)
                if not users:
                    del m["reactions"][emoji]
            else:
                users.append(reactor_id)
            self._notify_locked()
            return True

    def recall_message(self, peer_id: str, msg_id: str, requester_id: str) -> bool:
        with self.lock:
            m = self._find_msg_locked(peer_id, msg_id)
            if not m or m.get("sender_id") != requester_id or m.get("recalled"):
                return False
            m.update({"recalled": True, "text": "Tin nhắn đã được thu hồi", "reactions": {}, "file_path": None})
            self._notify_locked()
            return True

    def set_peer_typing(self, peer_id: str, is_typing: bool, ttl_sec: float = 5.0) -> None:
        with self.lock:
            if is_typing:
                self.typing_peers[peer_id] = time.time() + ttl_sec
            else:
                self.typing_peers.pop(peer_id, None)
            self._notify_locked()

    def cleanup_expired_typing(self) -> None:
        now = time.time()
        with self.lock:
            expired = [p for p, exp in self.typing_peers.items() if exp <= now]
            for p in expired:
                del self.typing_peers[p]
            if expired:
                self._notify_locked()

    def get_snapshot(self) -> dict:
        now = time.time()
        with self.lock:
            active_typing = {p for p, exp in self.typing_peers.items() if exp > now}
            offline_ids = [pid for pid, ms in self.messages.items() if pid not in self.online_peers and ms]
            all_ids = list(self.online_peers.keys()) + offline_ids

            name_counts: Dict[str, int] = {}
            for pid in all_ids:
                nm = self._get_peer_name_locked(pid)
                name_counts[nm] = name_counts.get(nm, 0) + 1

            peers_data = []
            for pid in all_ids:
                info = self.online_peers.get(pid)
                nm = info["name"] if info else self._get_peer_name_locked(pid)
                ep = self.peer_endpoints.get(pid)
                peers_data.append({
                    "peer_id": pid, "short_id": pid[:4], "name": nm,
                    "is_duplicate_name": (name_counts.get(nm, 0) > 1 or nm == self.my_name),
                    "ip": info["ip"] if info else (ep[0] if ep else ""),
                    "port": info["port"] if info else (ep[1] if ep else 0),
                    "status": info["status"] if info else "offline", "online": info is not None,
                    "can_reconnect": (info is not None or ep is not None),
                    "session_state": self.session_states.get(pid, "idle" if info else "disconnected"),
                    "typing": (pid in active_typing) if info else False,
                    "unread": self.unread_counts.get(pid, 0),
                    "last_preview": self._summarize_last(self.messages.get(pid, [])),
                })

            active_msgs = []
            if self.current_partner:
                for raw_m in self.messages.get(self.current_partner, []):
                    mc = dict(raw_m)
                    src_p = mc.pop("source_path", "")
                    if mc.get("kind") in ("file", "image") and mc.get("direction") == "out":
                        mc["can_server_retry"] = bool(src_p)
                    mc["reactions"] = {
                        em: [{"id": u, "name": "Bạn" if u == self.my_peer_id else self._get_peer_name_locked(u)} for u in uids]
                        for em, uids in (raw_m.get("reactions") or {}).items()
                    }
                    active_msgs.append(mc)

            return {
                "version": self._version,
                "running": self.running,
                "me": {
                    "peer_id": self.my_peer_id, "short_id": self.my_peer_id[:4], "name": self.my_name,
                    "tcp_port": self.my_tcp_port, "udp_port": self.my_udp_port,
                    "room": self.my_room, "status": self.my_status,
                },
                "current_partner": self.current_partner,
                "partner_session_state": self.session_states.get(self.current_partner, "idle") if self.current_partner else "idle",
                "partner_typing": bool(self.current_partner and self.current_partner in active_typing),
                "peers": peers_data,
                "messages": active_msgs,
                "terminal_entries": [dict(e) for e in self.terminal_entries[-200:]],
            }

    @staticmethod
    def _summarize_last(msgs: List[dict]) -> str:
        for m in reversed(msgs):
            if m.get("kind") == "cmd":
                continue
            if m.get("recalled"):
                return "Tin nhắn đã được thu hồi"
            if m.get("kind") == "image":
                return f"📷 {m.get('filename', 'Ảnh')}"
            if m.get("kind") == "file":
                return f"📎 {m.get('filename', 'Tệp')}"
            return m.get("text", "")[:42]
        return ""
