"""
main.py - Phụ trách: Linh
Điểm khởi chạy chương trình:
  1. Kiểm tra tham số dòng lệnh (--name, --tcp-port, --udp-port, --bcast).
  2. Khởi tạo AppState và ConsoleUI.
  3. Ghép nối UDPService (TV2) và TCPService (TV3) — có chế độ chạy thử độc lập nếu
     2 phân hệ kia chưa hoàn thiện trong Ngày 1.
  4. Dọn dẹp socket an toàn (Graceful Shutdown) khi thoát chương trình.
"""
import argparse
import sys

from protocol import validate_peer_name
from state import AppState
from ui import ConsoleUI


def parse_args():
    parser = argparse.ArgumentParser(description="P2P LAN Chat & File Sharing (Console)")
    parser.add_argument("--name", required=True, help="Your display name (no spaces or '|')")
    parser.add_argument("--tcp-port", type=int, default=5000, help="Local TCP listening port (default: 5000)")
    parser.add_argument("--udp-port", type=int, default=9999, help="UDP discovery port (default: 9999)")
    parser.add_argument(
        "--bcast",
        default="255.255.255.255",
        help="Broadcast address (use 127.255.255.255 when testing multiple instances offline)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 1. Validate tham số đầu vào trước khi mở socket
    if not validate_peer_name(args.name):
        print("[!] Error: --name must not be empty or contain spaces / '|' characters.")
        sys.exit(1)

    if not (1024 <= args.tcp_port <= 65535):
        print("[!] Error: --tcp-port must be between 1024 and 65535.")
        sys.exit(1)

    # 2. Khởi tạo lõi trạng thái và giao diện
    state = AppState(name=args.name, tcp_port=args.tcp_port)
    ui = ConsoleUI(state)

    udp_service = None
    tcp_service = None

    # 3. Khởi tạo phân hệ TCP (TV3) và UDP (TV2)
    try:
        from tcp_service import TCPService
        tcp_service = TCPService(state, ui)
        tcp_service.start()
    except ImportError:
        ui.show_message("[!] Warning: tcp_service.py not found (running in UI-only mode).")
    except OSError as e:
        print(f"[!] Fatal Error: Cannot bind TCP port {args.tcp_port} ({e}). Try another --tcp-port.")
        sys.exit(1)

    try:
        from udp_service import UDPService
        udp_service = UDPService(state, ui, udp_port=args.udp_port, bcast_addr=args.bcast)
        udp_service.start()
    except ImportError:
        ui.show_message("[!] Warning: udp_service.py not found (running in UI-only mode).")
    except OSError as e:
        print(f"[!] Fatal Error: Cannot bind UDP port {args.udp_port} ({e}).")
        sys.exit(1)

    ui.show_message(f"[*] Welcome {args.name}! Type /help for available commands.")

    # 4. Chạy vòng lặp nhập liệu trên Main Thread cho tới khi /quit hoặc Ctrl+C
    try:
        ui.run_input_loop(tcp_service)
    finally:
        # Dọn dẹp tài nguyên trước khi thoát hẳn
        state.stop()
        if tcp_service and hasattr(tcp_service, "shutdown"):
            tcp_service.shutdown()
        if udp_service and hasattr(udp_service, "shutdown"):
            udp_service.shutdown()


if __name__ == "__main__":
    main()