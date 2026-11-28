import os
import sys
import threading
from typing import Optional

from protocol import SHORT_HELP_TEXT

if os.name == "nt":
    import msvcrt
    os.system("")

    def _get_key() -> Optional[str]:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            return None
        return ch

    _setup_terminal = lambda: None
    _restore_terminal = lambda _: None
else:
    import termios
    import tty

    def _get_key() -> Optional[str]:
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            sys.stdin.read(2)
            return None
        return ch

    def _setup_terminal():
        old = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return old

    def _restore_terminal(old):
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)

def execute_command(state, tcp_service, line: str, is_cli: bool = False) -> dict:
    def reply(output: str = "", *, ok: bool = True, toast: str = "", clear: bool = False, quit_app: bool = False, history=None) -> dict:
        return {"ok": ok, "output": output, "toast": toast, "clear": clear, "quit": quit_app, "history": history or []}

    parts = line.strip().split(" ", 1)
    cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")

    if cmd == "/help":
        return reply(SHORT_HELP_TEXT)
    if cmd == "/clear":
        return reply("[*] Terminal cleared.", clear=True)
    if cmd == "/list":
        peers = state.get_peer_list()
        if not peers:
            return reply("[*] Không có peer nào khác đang online.")
        rows = ["Online users:"] + [
            f"  {i}. {info['name']:<12} [#{pid[:4]}]  {info['ip']}:{info['port']}  [{info['status']}]"
            + (f" ({unread} unread)" if unread > 0 else "")
            for i, (pid, info, unread) in enumerate(peers, 1)
        ]
        return reply("\n".join(rows))
    if cmd == "/status":
        if arg not in ("online", "away"):
            return reply("[!] Usage: /status <online|away>", ok=False)
        state.set_status(arg)
        if tcp_service:
            tcp_service.broadcast_status_tcp(arg)
        return reply(f"[*] Status changed to '{arg}'.", toast=f"Đã đổi trạng thái sang {arg}")
    if cmd == "/chat":
        if not arg:
            return reply("[!] Usage: /chat <tên|số|peer_id>", ok=False)
        pid, info, amb = state.get_peer_by_identifier(arg)
        if amb:
            rows = [f"[!] Có {len(amb)} máy trùng tên '{arg}'. Chọn bằng STT (/list) hoặc mã ID:"] + [
                f"    - {x['name']} [#{p[:4]}] ({x['ip']}:{x['port']})" for p, x in amb
            ]
            return reply("\n".join(rows), ok=False)
        if not pid or not info:
            return reply(f"[!] User '{arg}' not found or offline.", ok=False)
        reconnected = False
        if state.is_session_disconnected(pid):
            if not state.get_peer_by_id(pid):
                state.set_current_partner(pid)
                return reply(f"[!] User '{info['name']}' is offline.", ok=False)
            if tcp_service:
                ok_r, err = tcp_service.reconnect(pid)
                if not ok_r:
                    return reply(f"[!] Không thể kết nối lại TCP tới {info['name']}: {err}", ok=False)
            reconnected = True
        elif tcp_service:
            ok_o, err = tcp_service.open_chat(pid)
            if not ok_o:
                return reply(f"[!] Không thể kết nối TCP tới {info['name']}: {err}", ok=False)
        unread, history = state.set_current_partner(pid)
        if tcp_service:
            tcp_service.notify_seen(pid)
        note = f"\n[*] Note: {info['name']} is currently away." if info.get("status") == "away" else ""
        action = "Reconnected & switched to" if reconnected else "Switched to"
        return reply(
            f"[*] {action} {info['name']} [#{pid[:4]}] ({info['ip']}:{info['port']}) — {unread} unread.{note}",
            toast=f"Đang chat với {info['name']}", history=history[-15:],
        )
    if cmd == "/leave":
        pid = state.get_current_partner()
        if not pid or state.is_session_disconnected(pid):
            return reply("[!] You are not in any active chat.", ok=False)
        pname = state.get_peer_name(pid)
        tcp_service.close_chat(pid) if tcp_service else state.set_session_state(pid, "disconnected")
        return reply(
            f"──────── Bạn đã rời cuộc trò chuyện với {pname} [#{pid[:4]}] (gõ /reconnect để kết nối lại) ────────",
            toast=f"Đã rời cuộc trò chuyện với {pname}",
        )
    if cmd in ("/reconnect", "/connect"):
        target = state.get_last_partner()
        if arg:
            pid, _, amb = state.get_peer_by_identifier(arg)
            if amb:
                return reply(f"[!] Trùng tên '{arg}', hãy dùng /reconnect <STT|peer_id>.", ok=False)
            target = pid
        if not target:
            return reply("[!] Usage: /reconnect [tên|số|peer_id]", ok=False)
        if not state.get_peer_endpoint(target):
            return reply(f"[!] User '{state.get_peer_name(target)}' is offline.", ok=False)
        if not tcp_service:
            return reply("[!] TCPService chưa sẵn sàng.", ok=False)
        ok_r, err = tcp_service.reconnect(target)
        if not ok_r:
            return reply(f"[!] {err}", ok=False)
        state.set_current_partner(target)
        pname = state.get_peer_name(target)
        return reply(f"[*] Đã kết nối lại TCP với {pname} [#{target[:4]}].", toast=f"Đã kết nối lại với {pname}")
    if cmd == "/send":
        pid, filepath = state.get_current_partner(), arg.strip('"').strip("'")
        if not pid:
            return reply("[!] Select a chat partner first using /chat <tên|số>.", ok=False)
        if state.is_session_disconnected(pid):
            return reply(f"[!] Đã ngắt kết nối với {state.get_peer_name(pid)}. Gõ /reconnect trước khi gửi tệp.", ok=False)
        if not filepath or not os.path.isfile(filepath):
            return reply(f"[!] File not found: '{filepath}'", ok=False)
        if tcp_service and not tcp_service.send_file_async(pid, filepath):
            return reply(f"[!] Không thể gửi tệp tới {state.get_peer_name(pid)}.", ok=False)
        fname = os.path.basename(filepath)
        return reply(f"[*] Bắt đầu truyền '{fname}' tới {state.get_peer_name(pid)}...", toast=f"Đang gửi {fname}...")
    if cmd == "/transfers":
        items = tcp_service.get_active_transfers() if tcp_service else []
        if not items:
            return reply("[*] Hiện không có tệp nào đang gửi hoặc nhận.")
        rows = ["Đang truyền tệp:"] + [
            f"  #{it['short_id']} [{'SEND' if it['direction'] == 'out' else 'RECV'}] {it['filename']} "
            f"{'->' if it['direction'] == 'out' else '<-'} {it['peer_name']}"
            + (f"  {tcp_service._format_progress_bar(it['progress'], 16)}" if is_cli else "")
            + f"  {it['progress']:3d}%  {tcp_service._format_size_pair(it['transferred_bytes'], it['file_size'])}"
            + (f" ({it['speed_str']})" if it.get("speed_str") else "")
            for it in items
        ]
        return reply("\n".join(rows))
    if cmd == "/cancel":
        cancelled = tcp_service.cancel_active_transfers(arg) if tcp_service else []
        if not cancelled:
            msg = f"[!] Không tìm thấy tiến trình truyền tệp nào khớp '{arg}'." if arg else "[!] Hiện không có tệp nào đang gửi hoặc nhận để hủy."
            return reply(msg, ok=False)
        desc = ", ".join(f"{'SEND' if m['direction'] == 'out' else 'RECV'} #{m['short_id']} ({m['filename']})" for m in cancelled)
        return reply(f"[*] Đã hủy {len(cancelled)} tiến trình: {desc}", toast=f"Đã hủy {len(cancelled)} tiến trình truyền tệp")
    if cmd in ("/delete", "/clear-chat"):
        pid = state.get_current_partner()
        if not pid:
            return reply("[!] Chưa chọn đoạn chat nào để xóa.", ok=False)
        pname = state.get_peer_name(pid)
        state.delete_conversation(pid)
        return reply(f"[*] Đã xóa đoạn chat với {pname} [#{pid[:4]}].", toast=f"Đã xóa đoạn chat với {pname}")
    if cmd == "/quit":
        return reply("[*] Đang thoát chương trình an toàn...", quit_app=True)
    return reply(f"[!] Unknown command '{cmd}'.\n{SHORT_HELP_TEXT}", ok=False)

class ConsoleUI:
    CLEAR_LINE = "\r\033[K"

    def __init__(self, state):
        self.state = state
        self.buffer: str = ""
        self.screen_lock = threading.Lock()

    def _get_prompt(self) -> str:
        pid = self.state.get_current_partner()
        if not pid or self.state.is_session_disconnected(pid):
            return "> "
        return f"[{self.state.format_peer_label(pid)}] > "

    def show_message(self, line: str) -> None:
        self.state.add_log(line)
        with self.screen_lock:
            sys.stdout.write(f"{self.CLEAR_LINE}{line}\n{self._get_prompt()}{self.buffer}")
            sys.stdout.flush()

    def handle_command(self, line: str, tcp_service) -> None:
        res = execute_command(self.state, tcp_service, line, is_cli=True)
        if res["clear"]:
            os.system("cls" if os.name == "nt" else "clear")
        if res["quit"]:
            self.state.stop()
            return
        if res["output"]:
            self.show_message(res["output"])
        for msg in res["history"]:
            self.show_message(msg)

    def run_input_loop(self, tcp_service=None) -> None:
        old_settings = _setup_terminal()
        with self.screen_lock:
            sys.stdout.write(self._get_prompt())
            sys.stdout.flush()
        try:
            while self.state.is_running():
                ch = _get_key()
                if ch is None:
                    continue
                text_to_send = cmd_to_run = None
                with self.screen_lock:
                    if ch in ("\r", "\n"):
                        raw, self.buffer = self.buffer, ""
                        sys.stdout.write(self.CLEAR_LINE)
                        if not raw.strip():
                            sys.stdout.write(self._get_prompt())
                        elif raw.startswith("/"):
                            cmd_to_run = raw
                            sys.stdout.write(self._get_prompt())
                        else:
                            pid = self.state.get_current_partner()
                            if not pid:
                                sys.stdout.write(f"[!] No active chat. Use /list and /chat <tên|số>.\n{self._get_prompt()}")
                            elif self.state.is_session_disconnected(pid):
                                sys.stdout.write(f"[!] Đã ngắt kết nối với {self.state.get_peer_name(pid)}. Gõ /reconnect để kết nối lại.\n{self._get_prompt()}")
                            else:
                                fmt = f"[{self.state.my_name}#{self.state.my_peer_id[:4]}] {raw}"
                                sys.stdout.write(f"{fmt}\n{self._get_prompt()}")
                                mid = self.state.record_outgoing_message(pid, fmt, raw_text=raw)
                                text_to_send = (pid, raw, mid)
                        sys.stdout.flush()
                    elif ch in ("\b", "\x7f") and self.buffer:
                        self.buffer = self.buffer[:-1]
                        sys.stdout.write(f"{self.CLEAR_LINE}{self._get_prompt()}{self.buffer}")
                        sys.stdout.flush()
                    elif ch == "\x03":
                        self.state.stop()
                        break
                    elif ch.isprintable():
                        self.buffer += ch
                        sys.stdout.write(ch)
                        sys.stdout.flush()

                if cmd_to_run:
                    self.handle_command(cmd_to_run, tcp_service)
                    if not self.state.is_running():
                        break
                elif text_to_send and tcp_service:
                    tcp_service.send_message(*text_to_send)
        finally:
            _restore_terminal(old_settings)
            print("\n[*] Bye!")
