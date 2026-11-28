import argparse
import os
import socket
import sys

from protocol import load_or_create_peer_id, validate_peer_id, validate_peer_name, validate_room_name
from state import AppState
from tcp_service import TCPService
from udp_service import UDPService

DEFAULT_ROOM, DEFAULT_TCP_START, DEFAULT_UDP_PORT = "N08", 5000, 9999

def find_available_tcp_port(start_port: int = DEFAULT_TCP_START, max_tries: int = 100) -> int:
    for port in range(start_port, min(start_port + max_tries, 65536)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise OSError(f"No available TCP port in {start_port}..{start_port + max_tries - 1}")

def parse_args():
    p = argparse.ArgumentParser(description="P2P LAN Chat & File Sharing (GUI & CLI - v7.16)")
    p.add_argument("--name", default="", help="Tên hiển thị (không dấu cách hoặc '|')")
    p.add_argument("--peer-id", default="", help="Ghi đè mã định danh (mặc định nạp từ .peer_ids.json)")
    p.add_argument("--tcp-port", type=int, default=0, help="Cổng TCP (0 = tự chọn cổng trống từ 5000)")
    p.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help="Cổng UDP Discovery (mặc định: 9999)")
    p.add_argument("--room", default=DEFAULT_ROOM, help=f"Tên phòng LAN (mặc định: {DEFAULT_ROOM})")
    p.add_argument("--bcast", default="255.255.255.255", help="Địa chỉ Broadcast UDP")
    p.add_argument("--cli", action="store_true", help="Chạy giao diện Console (CLI)")
    p.add_argument("--web-port", type=int, default=0, help="Cổng Web GUI nội bộ")
    p.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    p.add_argument("--idle-shutdown", type=float, default=7.0, help="Tự thoát sau N giây đóng hết tab web (0 = tắt)")
    p.add_argument("--file-speed-mb", type=float, default=0.0, help="Giới hạn tốc độ gửi file MB/s để demo (0 = tối đa)")
    return p.parse_args()

def main():
    args = parse_args()
    name = args.name.strip()
    if not name:
        while not validate_peer_name(name):
            try:
                name = input("Tên hiển thị (không dấu cách): ").strip()
            except (EOFError, KeyboardInterrupt):
                sys.exit(0)
            if not validate_peer_name(name):
                print("[!] Tên không được rỗng hoặc chứa dấu cách / '|'. Hãy nhập lại.")
    elif not validate_peer_name(name):
        sys.exit("[!] Error: invalid --name.")

    room = args.room.strip() or DEFAULT_ROOM
    if not validate_room_name(room):
        sys.exit("[!] Error: invalid --room.")
    bcast = args.bcast.strip() or "255.255.255.255"

    try:
        tcp_port = find_available_tcp_port(DEFAULT_TCP_START) if args.tcp_port == 0 else args.tcp_port
    except OSError as e:
        sys.exit(f"[!] Fatal Error: {e}")
    if not (1024 <= tcp_port <= 65535):
        sys.exit("[!] Error: --tcp-port must be 1024..65535.")

    peer_id = args.peer_id.strip() or load_or_create_peer_id(room, name, tcp_port)
    if not validate_peer_id(peer_id):
        sys.exit("[!] Error: invalid --peer-id.")

    state = AppState(name=name, tcp_port=tcp_port, udp_port=args.udp_port, room=room, peer_id=peer_id)
    if args.cli:
        from ui import ConsoleUI
        ui = ConsoleUI(state)
    else:
        from web_ui import WebUI
        ui = WebUI(state, web_port=args.web_port, idle_shutdown_sec=args.idle_shutdown)

    tcp_service = TCPService(state, ui, max_file_speed_mb=args.file_speed_mb)
    udp_service = None
    try:
        tcp_service.start()
        udp_service = UDPService(state, ui, args.udp_port, bcast, room=room, on_peer_timeout=tcp_service.drop_peer)
        udp_service.start()
    except OSError as e:
        tcp_service.shutdown()
        sys.exit(f"[!] Fatal Error: {e}")

    ui.show_message(f"[*] Welcome {name} [#{peer_id[:4]}]! Room:{room} | UDP:{args.udp_port} | TCP:{tcp_port} | Bcast:{bcast}")
    try:
        if args.cli:
            ui.run_input_loop(tcp_service)
        else:
            ui.run_input_loop(tcp_service, open_browser=not args.no_browser)
    finally:
        state.stop()
        tcp_service.shutdown()
        if udp_service:
            udp_service.shutdown()
        if hasattr(ui, "shutdown"):
            ui.shutdown()
        print("[*] Bye!")

if __name__ == "__main__":
    main()
