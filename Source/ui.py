"""
ui.py - Phụ trách: Linh
Giao diện Console chống trôi dòng nhập liệu (Manual Redraw) + Bộ phân tích lệnh CLI.
Hỗ trợ:
  - Nhận tin nhắn từ nhiều luồng nền mà không làm mất chữ người dùng đang gõ (\r\033[K).
  - Hiển thị dấu nhắc động: `[Minh] > ` khi đang chat với Minh, `> ` khi ở sảnh chính.
  - Phân tích toàn bộ lệnh: /list, /chat, /send, /leave, /status, /help, /quit.
"""
import os
import sys
import threading
from typing import Optional

# Xử lý đọc từng phím không cần nhấn Enter trên cả Windows và Linux/macOS
if os.name == "nt":
    import msvcrt
    os.system("")  # Kích hoạt hỗ trợ mã màu/điều khiển ANSI (\033[K) trên Windows CMD/PowerShell

    def _get_key() -> Optional[str]:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # Phím mũi tên, F1..F12 gửi 2 mã -> bỏ qua mã thứ 2
            msvcrt.getwch()
            return None
        return ch

    def _setup_terminal():
        return None

    def _restore_terminal(_):
        pass
else:
    import termios
    import tty

    def _get_key() -> Optional[str]:
        ch = sys.stdin.read(1)
        if ch == "\x1b":  # Phím mũi tên (ESC [ A) -> bỏ qua
            sys.stdin.read(2)
            return None
        return ch

    def _setup_terminal():
        old = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return old

    def _restore_terminal(old):
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


class ConsoleUI:
    CLEAR_LINE = "\r\033[K"

    def __init__(self, state):
        self.state = state
        self.buffer: str = ""
        self.screen_lock = threading.Lock()

    def _get_prompt(self) -> str:
        """Tạo dấu nhắc động giúp người dùng biết mình đang chat với ai."""
        partner = self.state.get_current_partner()
        return f"[{partner}] > " if partner else "> "

    def show_message(self, line: str) -> None:
        """
        In một dòng thông báo phía trên dòng nhập liệu hiện tại.
        An toàn khi gọi đồng thời từ mọi luồng (UDP, TCP Receiver, File Sender).
        """
        with self.screen_lock:
            prompt = self._get_prompt()
            sys.stdout.write(self.CLEAR_LINE)
            sys.stdout.write(line + "\n")
            sys.stdout.write(prompt + self.buffer)
            sys.stdout.flush()

    def print_help(self) -> None:
        help_text = (
            "Available commands:\n"
            "  /list                 - Show online users\n"
            "  /chat <name|number>   - Open chat with a peer\n"
            "  /send <filepath>      - Send file to current chat partner\n"
            "  /leave                - Close current chat\n"
            "  /status <online|away> - Change your status\n"
            "  /help                 - Show this help\n"
            "  /quit                 - Exit program"
        )
        self.show_message(help_text)

    def handle_command(self, line: str, tcp_service) -> None:
        """Phân tích và thực thi các lệnh bắt đầu bằng dấu '/'."""
        parts = line.strip().split(" ", 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            self.print_help()

        elif cmd == "/list":
            peers = self.state.get_peer_list()
            if not peers:
                self.show_message("[*] No other peers online.")
            else:
                lines = ["Online users:"]
                for idx, (name, info, unread) in enumerate(peers, 1):
                    unread_tag = f" ({unread} unread)" if unread > 0 else ""
                    lines.append(
                        f"  {idx}. {name:<12} ({info['ip']}:{info['port']})  [{info['status']}]{unread_tag}"
                    )
                self.show_message("\n".join(lines))

        elif cmd == "/status":
            if arg not in ("online", "away"):
                self.show_message("[!] Usage: /status <online|away>")
            else:
                self.state.set_status(arg)
                self.show_message(f"[*] Status changed to '{arg}'.")

        elif cmd == "/chat":
            if not arg:
                self.show_message("[!] Usage: /chat <name|number>")
                return

            peer_name, peer_info = self.state.get_peer_by_identifier(arg)
            if not peer_name:
                self.show_message(f"[!] User '{arg}' not found or offline.")
                return

            unread, history = self.state.set_current_partner(peer_name)
            self.show_message(
                f"[*] Switched to {peer_name} ({peer_info['ip']}:{peer_info['port']}) — {unread} unread:"
            )
            if peer_info.get("status") == "away":
                self.show_message(f"[*] Note: {peer_name} is currently away.")

            # In tối đa 15 tin nhắn gần nhất trong lịch sử
            for msg in history[-15:]:
                self.show_message(msg)

        elif cmd == "/leave":
            partner = self.state.get_current_partner()
            if not partner:
                self.show_message("[!] You are not in any active chat.")
            else:
                if tcp_service:
                    tcp_service.close_chat(partner)
                self.state.set_current_partner(None)
                self.show_message(f"[*] Left chat with {partner}.")

        elif cmd == "/send":
            partner = self.state.get_current_partner()
            if not partner:
                self.show_message("[!] Select a chat partner first using /chat <name>.")
                return

            # Xóa dấu ngoặc kép nếu người dùng kéo thả file có dấu cách vào terminal
            filepath = arg.strip('"').strip("'")
            if not filepath or not os.path.isfile(filepath):
                self.show_message(f"[!] File not found: '{filepath}'")
                return

            if tcp_service:
                tcp_service.send_file_async(partner, filepath)

        elif cmd == "/quit":
            self.state.stop()

        else:
            self.show_message(f"[!] Unknown command '{cmd}'. Type /help for commands.")

    def run_input_loop(self, tcp_service=None) -> None:
        """Vòng lặp đọc bàn phím chạy trên Main Thread."""
        old_settings = _setup_terminal()

        with self.screen_lock:
            sys.stdout.write(self._get_prompt())
            sys.stdout.flush()

        try:
            while self.state.is_running():
                ch = _get_key()
                if ch is None:
                    continue

                text_to_send = None
                command_to_run = None

                # Chỉ giữ screen_lock trong lúc cập nhật buffer và vẽ lại dòng nhập liệu
                with self.screen_lock:
                    if ch in ("\r", "\n"):  # Nhấn Enter
                        raw_text = self.buffer
                        self.buffer = ""
                        sys.stdout.write(self.CLEAR_LINE)

                        if not raw_text.strip():
                            sys.stdout.write(self._get_prompt())
                            sys.stdout.flush()
                            continue

                        if raw_text.startswith("/"):
                            command_to_run = raw_text
                            sys.stdout.write(self._get_prompt())
                            sys.stdout.flush()
                        else:
                            partner = self.state.get_current_partner()
                            if not partner:
                                sys.stdout.write(
                                    "[!] No active chat. Use /list and /chat <name>.\n"
                                    + self._get_prompt()
                                )
                                sys.stdout.flush()
                                continue

                            formatted = f"[{self.state.my_name}] {raw_text}"
                            sys.stdout.write(formatted + "\n" + self._get_prompt())
                            sys.stdout.flush()
                            self.state.record_outgoing_message(partner, formatted)
                            text_to_send = (partner, raw_text)

                    elif ch in ("\b", "\x7f"):  # Nhấn Backspace
                        if self.buffer:
                            self.buffer = self.buffer[:-1]
                            sys.stdout.write(self.CLEAR_LINE + self._get_prompt() + self.buffer)
                            sys.stdout.flush()

                    elif ch == "\x03":  # Nhấn Ctrl+C
                        self.state.stop()
                        break

                    elif ch.isprintable():  # Ký tự gõ bình thường (hỗ trợ cả tiếng Việt)
                        self.buffer += ch
                        sys.stdout.write(ch)
                        sys.stdout.flush()

                # Thực thi mạng hoặc lệnh SAU KHI đã nhả screen_lock để tránh nghẽn giao diện
                if command_to_run:
                    self.handle_command(command_to_run, tcp_service)
                    if not self.state.is_running():
                        break
                elif text_to_send and tcp_service:
                    partner, raw_text = text_to_send
                    tcp_service.send_message(partner, raw_text)

        finally:
            _restore_terminal(old_settings)
            print("\n[*] Bye!")