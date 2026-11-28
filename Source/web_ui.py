import json
import mimetypes
import os
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from protocol import sanitize_filename
from ui import execute_command

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LAN Chat & File Sharing</title>
<style>
  :root { --accent: #0068ff; --accent-hover: #0054d1; --accent-soft: rgba(0, 104, 255, 0.11); --accent-grad: linear-gradient(135deg, #0a84ff 0%, #0058e6 100%); --rail-bg: #005be0; --rail-bg-grad: linear-gradient(180deg, #0068ff 0%, #004ec2 100%); --rail-hover: rgba(255, 255, 255, 0.16); --rail-active: rgba(255, 255, 255, 0.24); --bg-app: #edf1f7; --bg-sidebar: #ffffff; --bg-header: rgba(255, 255, 255, 0.92); --bg-surface: #f3f5f9; --bg-surface-2: #e9eef5; --bg-hover: #f0f4fa; --bg-active: #e7f1ff; --border: #e4e9f2; --border-strong: #d3dce8; --text-main: #0f172a; --text-sub: #64748b; --text-muted: #94a3b8; --bubble-in: #ffffff; --bubble-in-text: #0f172a; --bubble-in-border: rgba(15, 23, 42, 0.06); --bubble-sys: rgba(15, 23, 42, 0.07); --online: #22c55e; --away: #f59e0b; --offline: #94a3b8; --danger: #ef4444; --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.05); --shadow-sm: 0 4px 14px rgba(15, 23, 42, 0.09); --shadow-md: 0 10px 30px rgba(15, 23, 42, 0.14); --pattern-color: rgba(15, 23, 42, 0.032); }
  [data-accent="violet"] { --accent: #6366f1; --accent-hover: #4f46e5; --accent-soft: rgba(99, 102, 241, 0.12); --accent-grad: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); --rail-bg: #4f46e5; --rail-bg-grad: linear-gradient(180deg, #6366f1 0%, #4338ca 100%); --bg-active: #eef2ff; }
  [data-accent="emerald"] { --accent: #059669; --accent-hover: #047857; --accent-soft: rgba(5, 150, 105, 0.12); --accent-grad: linear-gradient(135deg, #10b981 0%, #047857 100%); --rail-bg: #047857; --rail-bg-grad: linear-gradient(180deg, #059669 0%, #065f46 100%); --bg-active: #ecfdf5; }
  [data-accent="rose"] { --accent: #e11d48; --accent-hover: #be123c; --accent-soft: rgba(225, 29, 72, 0.11); --accent-grad: linear-gradient(135deg, #f43f5e 0%, #be123c 100%); --rail-bg: #be123c; --rail-bg-grad: linear-gradient(180deg, #e11d48 0%, #9f1239 100%); --bg-active: #fff1f2; }
  [data-theme="dark"] { --rail-bg: #0b1120; --rail-bg-grad: linear-gradient(180deg, #0f172a 0%, #090e1a 100%); --rail-hover: rgba(255, 255, 255, 0.08); --rail-active: rgba(255, 255, 255, 0.15); --bg-app: #0b1120; --bg-sidebar: #111827; --bg-header: rgba(17, 24, 39, 0.9); --bg-surface: #1e293b; --bg-surface-2: #273449; --bg-hover: #1a2436; --bg-active: rgba(59, 130, 246, 0.16); --border: #1e293b; --border-strong: #334155; --text-main: #f1f5f9; --text-sub: #94a3b8; --text-muted: #64748b; --bubble-in: #1e293b; --bubble-in-text: #f1f5f9; --bubble-in-border: rgba(255, 255, 255, 0.05); --bubble-sys: rgba(148, 163, 184, 0.13); --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.25); --shadow-sm: 0 4px 16px rgba(0, 0, 0, 0.36); --shadow-md: 0 12px 32px rgba(0, 0, 0, 0.5); --pattern-color: rgba(255, 255, 255, 0.028); }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: var(--bg-app); color: var(--text-main); overflow: hidden; -webkit-font-smoothing: antialiased; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.35); border-radius: 999px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(148, 163, 184, 0.58); }
  .app-shell { display: flex; height: 100vh; width: 100vw; overflow: hidden; }
  .nav-rail { width: 64px; background: var(--rail-bg-grad); display: flex; flex-direction: column; align-items: center; padding: 14px 0 14px; gap: 8px; flex-shrink: 0; z-index: 5; box-shadow: 2px 0 12px rgba(0, 0, 0, 0.08); position: relative; }
  .rail-avatar-btn { border: none; background: transparent; cursor: pointer; position: relative; margin-bottom: 10px; padding: 2px; border-radius: 50%; transition: transform 0.15s; }
  .rail-avatar-btn:hover { transform: scale(1.06); }
  .rail-avatar-btn .avatar { width: 42px; height: 42px; border: 2px solid rgba(255, 255, 255, 0.45); }
  .rail-avatar-btn .status-dot { border-color: var(--rail-bg); width: 13px; height: 13px; }
  .rail-group { display: flex; flex-direction: column; align-items: center; gap: 6px; width: 100%; }
  .rail-spacer { flex: 1; }
  .rail-btn { position: relative; width: 44px; height: 44px; border: none; border-radius: 13px; background: transparent; color: rgba(255, 255, 255, 0.82); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: background 0.15s, color 0.15s, transform 0.1s; }
  .rail-btn:hover { background: var(--rail-hover); color: #ffffff; }
  .rail-btn:active { transform: scale(0.94); }
  .rail-btn.active { background: var(--rail-active); color: #ffffff; }
  .rail-btn svg { width: 21px; height: 21px; stroke-width: 1.9; }
  .rail-badge { position: absolute; top: 4px; right: 4px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: #ef4444; color: #fff; font-size: 10px; font-weight: 700; display: none; align-items: center; justify-content: center; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25); }
  .rail-badge.show { display: inline-flex; }
  .accent-popover { position: fixed; left: 74px; bottom: 68px; background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: 14px; padding: 10px 12px; box-shadow: var(--shadow-md); display: none; align-items: center; gap: 8px; z-index: 40; }
  .accent-popover.open { display: flex; }
  .swatch { width: 24px; height: 24px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; transition: transform 0.12s; }
  .swatch:hover { transform: scale(1.16); }
  .swatch.selected { border-color: var(--text-main); transform: scale(1.1); }
  .sidebar { width: 316px; min-width: 268px; background: var(--bg-sidebar); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; z-index: 2; }
  .sidebar-top { padding: 16px 16px 12px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .brand-wrap { min-width: 0; }
  .brand-title { font-size: 18px; font-weight: 800; letter-spacing: -0.02em; color: var(--text-main); display: flex; align-items: center; gap: 7px; }
  .brand-sub { font-size: 11.5px; color: var(--text-sub); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .status-pill { display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px; font-size: 12px; font-weight: 700; border: 1px solid transparent; cursor: pointer; transition: all 0.15s; flex-shrink: 0; }
  .status-pill.online { background: rgba(34, 197, 94, 0.13); color: #16a34a; border-color: rgba(34, 197, 94, 0.28); }
  .status-pill.away { background: rgba(245, 158, 11, 0.14); color: #d97706; border-color: rgba(245, 158, 11, 0.3); }
  .status-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .search-box { margin: 0 14px 10px; position: relative; display: flex; align-items: center; }
  .search-box svg { position: absolute; left: 12px; width: 15px; height: 15px; color: var(--text-muted); pointer-events: none; }
  .search-input { width: 100%; padding: 9px 14px 9px 36px; border-radius: 12px; border: 1px solid transparent; background: var(--bg-surface); color: var(--text-main); font-size: 13.5px; outline: none; transition: all 0.15s; }
  .search-input:focus { background: var(--bg-sidebar); border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .filter-tabs { display: flex; gap: 6px; padding: 0 14px 10px; border-bottom: 1px solid var(--border); }
  .filter-tab { border: none; background: transparent; color: var(--text-sub); font-size: 12.5px; font-weight: 600; padding: 5px 11px; border-radius: 999px; cursor: pointer; transition: all 0.15s; }
  .filter-tab:hover { background: var(--bg-surface); color: var(--text-main); }
  .filter-tab.active { background: var(--accent-soft); color: var(--accent); }
  .peer-list { flex: 1; overflow-y: auto; padding: 8px 8px 14px; }
  .peer-item { display: flex; align-items: center; gap: 12px; padding: 10px 10px; border-radius: 14px; cursor: pointer; transition: background 0.14s, transform 0.1s; margin-bottom: 3px; position: relative; }
  .peer-item:hover { background: var(--bg-hover); }
  .peer-item.active { background: var(--bg-active); }
  .peer-item.active::before { content: ""; position: absolute; left: 2px; top: 12px; bottom: 12px; width: 3.5px; border-radius: 999px; background: var(--accent); }
  .avatar { width: 44px; height: 44px; border-radius: 50%; background: var(--accent-grad); color: #fff; font-weight: 700; font-size: 16px; display: flex; align-items: center; justify-content: center; position: relative; flex-shrink: 0; user-select: none; letter-spacing: -0.02em; }
  .avatar.sm { width: 40px; height: 40px; font-size: 15px; }
  .avatar.xs { width: 28px; height: 28px; font-size: 11.5px; }
  .avatar.lg { width: 64px; height: 64px; font-size: 24px; }
  .status-dot { position: absolute; bottom: 0; right: 0; width: 12px; height: 12px; border-radius: 50%; border: 2.2px solid var(--bg-sidebar); background: var(--online); }
  .status-dot.away { background: var(--away); }
  .status-dot.disconnected { background: var(--danger); }
  .status-dot.offline { background: var(--offline); }
  .peer-del-btn { opacity: 0; border: none; background: transparent; color: var(--text-muted); width: 26px; height: 26px; border-radius: 8px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; transition: opacity 0.14s, background 0.14s, color 0.14s; }
  .peer-del-btn svg { width: 14px; height: 14px; }
  .peer-item:hover .peer-del-btn { opacity: 1; }
  .peer-del-btn:hover { background: rgba(239, 68, 68, 0.13); color: var(--danger); }
  .peer-info { flex: 1; min-width: 0; }
  .peer-top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
  .peer-name { font-weight: 700; font-size: 14px; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .peer-ip { font-size: 10.5px; color: var(--text-muted); background: var(--bg-surface); padding: 1.5px 6px; border-radius: 6px; flex-shrink: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
  .peer-bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 3px; }
  .peer-preview { font-size: 12.5px; color: var(--text-sub); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .peer-preview.typing { color: var(--accent); font-style: italic; font-weight: 600; }
  .peer-item.has-unread .peer-preview { color: var(--text-main); font-weight: 600; }
  .unread-badge { min-width: 20px; height: 20px; padding: 0 6px; border-radius: 999px; background: var(--danger); color: #fff; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .empty-peers { text-align: center; padding: 46px 20px; color: var(--text-sub); font-size: 13px; line-height: 1.65; }
  .radar-wrap { width: 56px; height: 56px; margin: 0 auto 14px; position: relative; display: flex; align-items: center; justify-content: center; }
  .radar-core { width: 14px; height: 14px; border-radius: 50%; background: var(--accent); }
  .radar-ring { position: absolute; inset: 0; border-radius: 50%; border: 2px solid var(--accent); opacity: 0; animation: radarPulse 2s infinite ease-out; }
  .radar-ring:nth-child(2) { animation-delay: 0.7s; }
  @keyframes radarPulse {
  0% { transform: scale(0.35); opacity: 0.7; }
  100% { transform: scale(1.25); opacity: 0; }
  }
  .chat-panel { flex: 1; display: flex; flex-direction: column; background-color: var(--bg-app); background-image: radial-gradient(var(--pattern-color) 1.25px, transparent 1.25px); background-size: 20px 20px; position: relative; min-width: 0; }
  .chat-header { height: 68px; padding: 0 20px; background: var(--bg-header); backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 12px; z-index: 3; }
  .chat-partner-wrap { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .chat-partner-title { font-weight: 700; font-size: 15.5px; display: flex; align-items: center; gap: 8px; }
  .ip-chip { font-size: 11px; font-weight: 600; color: var(--text-sub); background: var(--bg-surface); border: 1px solid var(--border); padding: 2px 7px; border-radius: 999px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
  .chat-partner-sub { font-size: 12px; color: var(--text-sub); margin-top: 2px; display: flex; align-items: center; gap: 5px; }
  .chat-partner-sub.typing { color: var(--accent); font-weight: 600; }
  .header-actions { display: flex; align-items: center; gap: 6px; }
  .icon-btn { border: none; background: transparent; color: var(--text-sub); width: 36px; height: 36px; border-radius: 10px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: background 0.15s, color 0.15s, transform 0.1s; }
  .icon-btn svg { width: 19px; height: 19px; stroke-width: 1.9; }
  .icon-btn:hover { background: var(--bg-surface); color: var(--text-main); }
  .icon-btn:active { transform: scale(0.94); }
  .icon-btn.active { background: var(--accent-soft); color: var(--accent); }
  .icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .icon-btn.danger:hover { background: rgba(239, 68, 68, 0.12); color: var(--danger); }
  .btn-leave { border: 1px solid rgba(239, 68, 68, 0.26); background: rgba(239, 68, 68, 0.08); color: var(--danger); padding: 7px 12px; border-radius: 10px; font-size: 12.5px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; transition: all 0.15s; }
  .btn-leave:hover { background: rgba(239, 68, 68, 0.16); }
  .btn-leave svg { width: 15px; height: 15px; }
  .btn-reconnect { border: 1px solid rgba(0, 104, 255, 0.3); background: var(--accent-grad); color: #ffffff; padding: 7px 14px; border-radius: 10px; font-size: 12.5px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; box-shadow: 0 3px 10px rgba(0, 104, 255, 0.25); transition: opacity 0.15s, transform 0.1s; }
  .btn-reconnect:hover { opacity: 0.93; transform: translateY(-1px); }
  .btn-reconnect:active { transform: scale(0.96); }
  .btn-reconnect:disabled { opacity: 0.45; cursor: not-allowed; box-shadow: none; transform: none; }
  .btn-reconnect svg { width: 15px; height: 15px; }
  .divider-row { width: 100%; display: flex; align-items: center; gap: 12px; margin: 10px 0; color: var(--text-muted); font-size: 12px; font-weight: 600; letter-spacing: 0.01em; user-select: none; }
  .divider-row::before, .divider-row::after { content: ""; flex: 1; height: 1px; background: var(--border-strong); }
  .divider-row.danger { color: var(--danger); }
  .divider-row.danger::before, .divider-row.danger::after { background: rgba(239, 68, 68, 0.35); }
  .divider-row.ok { color: #16a34a; }
  .divider-row.ok::before, .divider-row.ok::after { background: rgba(34, 197, 94, 0.35); }
  .divider-row.warn { color: #d97706; }
  .divider-row.warn::before, .divider-row.warn::after { background: rgba(245, 158, 11, 0.35); }
  .divider-row span { padding: 3px 12px; border-radius: 999px; background: var(--bg-sidebar); border: 1px solid var(--border); white-space: nowrap; }
  .divider-row.danger span { border-color: rgba(239, 68, 68, 0.28); background: rgba(239, 68, 68, 0.06); }
  .divider-row.ok span { border-color: rgba(34, 197, 94, 0.28); background: rgba(34, 197, 94, 0.07); }
  .divider-row.warn span { border-color: rgba(245, 158, 11, 0.28); background: rgba(245, 158, 11, 0.07); }
  .disconnected-banner { display: none; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 20px; background: var(--bg-sidebar); border-top: 1px solid rgba(239, 68, 68, 0.28); box-shadow: 0 -4px 16px rgba(15, 23, 42, 0.05); }
  .disconnected-banner.show { display: flex; }
  .disconnected-info { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .disconnected-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger); flex-shrink: 0; }
  .disconnected-text { font-size: 13px; color: var(--text-main); font-weight: 600; }
  .disconnected-sub { font-size: 11.5px; color: var(--text-sub); margin-top: 1px; }
  .messages-area { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 20px 26px 18px; display: flex; flex-direction: column; gap: 10px; }
  .welcome-state { margin: auto; text-align: center; max-width: 440px; background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: 24px; padding: 36px 30px; box-shadow: var(--shadow-sm); }
  .welcome-icon { width: 68px; height: 68px; margin: 0 auto 18px; border-radius: 20px; background: var(--accent-grad); color: #fff; display: flex; align-items: center; justify-content: center; box-shadow: 0 10px 24px rgba(0, 104, 255, 0.28); }
  .welcome-icon svg { width: 32px; height: 32px; }
  .welcome-state h2 { font-size: 19px; font-weight: 800; margin-bottom: 8px; }
  .welcome-state p { font-size: 13.5px; color: var(--text-sub); line-height: 1.65; }
  .feature-chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; margin-top: 18px; }
  .feature-chip { font-size: 11.5px; font-weight: 600; color: var(--text-sub); background: var(--bg-surface); border: 1px solid var(--border); padding: 4px 10px; border-radius: 999px; }
  .msg-row { display: flex; flex-direction: column; max-width: min(82%, 100%); min-width: 0; position: relative; border-radius: 14px; transition: background 0.3s; }
  .msg-row.grouped { margin-top: -7px; }
  .msg-row.out { align-self: flex-end; align-items: flex-end; }
  .msg-row.in { align-self: flex-start; align-items: flex-start; }
  .msg-row.sys { align-self: center; align-items: center; max-width: 85%; margin: 4px 0; }
  .msg-row.new-anim { animation: msgPop 0.2s cubic-bezier(0.2, 0.9, 0.3, 1); }
  @keyframes msgPop {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
  }
  .msg-row.highlight { animation: flashRow 1.3s ease; }
  @keyframes flashRow {
  0%, 100% { background: transparent; }
  30% { background: var(--accent-soft); }
  }
  .msg-sender { font-size: 11px; font-weight: 700; color: var(--text-sub); margin: 0 0 3px 40px; }
  .msg-body-wrap { display: flex; align-items: flex-end; gap: 8px; position: relative; max-width: 100%; min-width: 0; }
  .msg-row.out .msg-body-wrap { flex-direction: row-reverse; }
  .in-avatar-slot { width: 28px; flex-shrink: 0; display: flex; align-items: flex-end; }
  .bubble-stack { display: flex; flex-direction: column; min-width: 0; max-width: 100%; flex: 0 1 auto; }
  .msg-row.out .bubble-stack { align-items: flex-end; }
  .msg-row.in .bubble-stack { align-items: flex-start; }
  .msg-actions { opacity: 0; pointer-events: none; display: inline-flex; align-items: center; gap: 1px; background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: 999px; padding: 3px 5px; box-shadow: var(--shadow-sm); transition: opacity 0.14s ease, transform 0.14s ease; transform: translateY(2px) scale(0.96); flex-shrink: 0; align-self: center; }
  .msg-row:hover .msg-actions, .msg-actions:focus-within { opacity: 1; pointer-events: auto; transform: translateY(0) scale(1); }
  .act-btn { border: none; background: transparent; color: var(--text-sub); cursor: pointer; width: 27px; height: 27px; border-radius: 50%; font-size: 14px; display: inline-flex; align-items: center; justify-content: center; transition: transform 0.12s, background 0.12s, color 0.12s; }
  .act-btn svg { width: 14px; height: 14px; }
  .act-btn:hover { background: var(--bg-surface); color: var(--text-main); transform: scale(1.16); }
  .act-btn.danger:hover { color: var(--danger); background: rgba(239, 68, 68, 0.1); }
  .act-sep { width: 1px; height: 15px; background: var(--border); margin: 0 3px; }
  .reply-quote { font-size: 12px; padding: 7px 11px 11px; margin-bottom: -7px; border-radius: 14px 14px 4px 4px; background: var(--bg-surface); border: 1px solid var(--border); border-left: 3px solid var(--accent); color: var(--text-sub); max-width: min(310px, 100%); cursor: pointer; overflow: hidden; transition: background 0.15s; }
  .reply-quote:hover { background: var(--bg-surface-2); }
  .reply-quote strong { display: block; font-size: 11px; color: var(--accent); margin-bottom: 1px; }
  .reply-quote span { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bubble { padding: 10px 14px; border-radius: 18px; font-size: 14px; line-height: 1.5; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; word-wrap: break-word; white-space: pre-wrap; box-shadow: var(--shadow-xs); position: relative; }
  .msg-row.out .bubble { background: var(--accent-grad); color: #ffffff; border-bottom-right-radius: 6px; }
  .msg-row.out.grouped .bubble { border-top-right-radius: 8px; }
  .msg-row.in .bubble { background: var(--bubble-in); color: var(--bubble-in-text); border: 1px solid var(--bubble-in-border); border-bottom-left-radius: 6px; }
  .msg-row.in.grouped .bubble { border-top-left-radius: 8px; }
  .msg-row.sys .bubble { background: var(--bubble-sys); color: var(--text-sub); font-size: 11.5px; font-weight: 500; padding: 5px 13px; border-radius: 999px; box-shadow: none; border: none; }
  .bubble.recalled { background: transparent !important; border: 1px dashed var(--border-strong) !important; color: var(--text-muted) !important; font-style: italic; font-size: 13px; box-shadow: none; }
  .reactions-bar { display: flex; flex-wrap: wrap; gap: 4px; margin-top: -7px; padding: 0 8px; z-index: 2; }
  .react-pill { display: inline-flex; align-items: center; gap: 3px; padding: 2px 7px; border-radius: 999px; background: var(--bg-sidebar); border: 1px solid var(--border); box-shadow: var(--shadow-xs); font-size: 12.5px; cursor: pointer; color: var(--text-main); transition: transform 0.12s, border-color 0.15s; }
  .react-pill:hover { transform: scale(1.1); }
  .react-pill.mine { border-color: var(--accent); background: var(--bg-active); }
  .react-count { font-size: 11px; font-weight: 700; color: var(--text-sub); }
  .msg-meta { display: inline-flex; align-items: center; gap: 6px; font-size: 10.5px; color: var(--text-muted); margin-top: 3px; padding: 0 4px; }
  .msg-row.in .msg-meta { margin-left: 36px; }
  .receipt { font-weight: 600; display: inline-flex; align-items: center; gap: 3px; }
  .receipt.sent { color: var(--text-muted); }
  .receipt.seen { color: var(--accent); }
  .receipt.sending { color: var(--text-muted); font-style: italic; }
  .receipt.failed { color: var(--danger); }
  .bubble.failed-bubble { opacity: 0.78; box-shadow: 0 0 0 1.5px var(--danger); }
  .retry-btn { border: 1px solid rgba(239, 68, 68, 0.35); background: rgba(239, 68, 68, 0.1); color: var(--danger); font-size: 10.5px; font-weight: 700; padding: 1.5px 8px; border-radius: 999px; cursor: pointer; transition: background 0.14s, color 0.14s; }
  .retry-btn:hover { background: var(--danger); color: #fff; }
  .hash-row { display: flex; align-items: center; gap: 6px; margin-top: 5px; flex-wrap: wrap; }
  .speed-chip { font-size: 10.5px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 2px 7px; border-radius: 999px; }
  .id-tag { display: inline-flex; align-items: center; font-size: 10px; font-weight: 700; color: var(--text-sub); background: var(--bg-surface-2); border: 1px solid var(--border); padding: 1px 5px; border-radius: 5px; margin-left: 5px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; vertical-align: middle; }
  .room-badge { display: inline-flex; align-items: center; font-size: 10.5px; font-weight: 700; color: var(--accent); background: var(--accent-soft); padding: 1.5px 7px; border-radius: 999px; vertical-align: middle; }
  .media-card { border-radius: 16px; overflow: hidden; background: var(--bg-sidebar); border: 1px solid var(--border); box-shadow: var(--shadow-sm); max-width: 320px; position: relative; }
  .media-img-wrap { position: relative; overflow: hidden; background: var(--bg-surface); }
  .media-card img { display: block; max-width: 318px; max-height: 270px; width: auto; height: auto; object-fit: cover; cursor: zoom-in; transition: transform 0.25s ease; }
  .media-img-wrap:hover img { transform: scale(1.02); }
  .media-dl-fab { position: absolute; top: 8px; right: 8px; width: 32px; height: 32px; border-radius: 50%; background: rgba(15, 23, 42, 0.65); color: #fff; display: flex; align-items: center; justify-content: center; text-decoration: none; opacity: 0; transition: opacity 0.15s, background 0.15s; backdrop-filter: blur(4px); }
  .media-img-wrap:hover .media-dl-fab { opacity: 1; }
  .media-dl-fab:hover { background: rgba(15, 23, 42, 0.88); }
  .media-dl-fab svg { width: 15px; height: 15px; }
  .media-footer { padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12px; }
  .media-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
  .media-size { color: var(--text-muted); font-size: 11px; flex-shrink: 0; }
  .file-card { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 16px; background: var(--bg-sidebar); border: 1px solid var(--border); min-width: min(290px, 100%); max-width: min(410px, 100%); box-shadow: var(--shadow-xs); }
  .zalo-prog-row { display: flex; align-items: center; gap: 9px; margin-top: 7px; }
  .zalo-prog-track { flex: 1; min-width: 96px; height: 6px; background: var(--bg-surface-2); border-radius: 999px; overflow: hidden; }
  .zalo-prog-fill { height: 100%; background: var(--accent-grad); border-radius: 999px; transition: width 0.14s ease; min-width: 6px; }
  .zalo-prog-fill.done { background: linear-gradient(90deg, #22c55e, #16a34a); }
  .zalo-prog-fill.failed, .zalo-prog-fill.cancelled { background: var(--danger); }
  .zalo-prog-bytes { font-size: 11.5px; font-weight: 600; color: var(--text-sub); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .zalo-cancel-btn { width: 22px; height: 22px; border-radius: 50%; border: none; background: var(--bg-surface-2); color: var(--text-sub); font-size: 13px; font-weight: 700; line-height: 1; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; transition: background 0.14s, color 0.14s, transform 0.1s; }
  .zalo-cancel-btn:hover { background: rgba(239, 68, 68, 0.18); color: var(--danger); transform: scale(1.08); }
  .file-ext { width: 44px; height: 44px; border-radius: 12px; background: var(--accent-soft); color: var(--accent); font-weight: 800; font-size: 11px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; text-transform: uppercase; }
  .file-ext.pdf { background: rgba(239, 68, 68, 0.12); color: #dc2626; }
  .file-ext.zip { background: rgba(245, 158, 11, 0.14); color: #d97706; }
  .file-ext.code { background: rgba(139, 92, 246, 0.14); color: #7c3aed; }
  .file-ext.media { background: rgba(236, 72, 153, 0.14); color: #db2777; }
  .file-meta { flex: 1; min-width: 0; }
  .file-name { font-weight: 600; font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .file-sub { font-size: 11.5px; color: var(--text-sub); margin-top: 2px; }
  .file-sub.err { color: var(--danger); }
  .file-dl-btn { width: 34px; height: 34px; border-radius: 10px; background: var(--accent-soft); color: var(--accent); display: inline-flex; align-items: center; justify-content: center; text-decoration: none; flex-shrink: 0; transition: background 0.15s; }
  .file-dl-btn:hover { background: var(--accent); color: #fff; }
  .file-dl-btn svg { width: 16px; height: 16px; }
  .file-retry-btn { border: 1px solid rgba(0, 104, 255, 0.28); background: var(--accent-soft); color: var(--accent); padding: 6px 11px; border-radius: 10px; font-size: 12px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; white-space: nowrap; transition: background 0.15s, color 0.15s, transform 0.1s; }
  .file-retry-btn:hover { background: var(--accent); color: #fff; }
  .file-retry-btn:active { transform: scale(0.95); }
  .file-retry-btn svg { width: 13px; height: 13px; }
  .typing-row { display: flex; align-items: flex-end; gap: 8px; align-self: flex-start; margin-top: 2px; animation: msgPop 0.2s ease; }
  .typing-bubble { background: var(--bubble-in); border: 1px solid var(--bubble-in-border); padding: 11px 15px; border-radius: 18px; border-bottom-left-radius: 6px; display: inline-flex; align-items: center; gap: 5px; box-shadow: var(--shadow-xs); }
  .typing-bubble span { width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted); animation: bounceDot 1.2s infinite ease-in-out; }
  .typing-bubble span:nth-child(2) { animation-delay: 0.15s; }
  .typing-bubble span:nth-child(3) { animation-delay: 0.3s; }
  @keyframes bounceDot {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-5px); opacity: 1; }
  }
  .scroll-fab { position: absolute; right: 24px; bottom: 84px; width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--border); background: var(--bg-sidebar); color: var(--text-main); box-shadow: var(--shadow-sm); cursor: pointer; display: none; align-items: center; justify-content: center; z-index: 6; transition: transform 0.15s; }
  .scroll-fab.show { display: inline-flex; }
  .scroll-fab:hover { transform: translateY(-2px); color: var(--accent); }
  .scroll-fab svg { width: 18px; height: 18px; }
  .reply-banner { display: none; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 20px; background: var(--bg-sidebar); border-top: 1px solid var(--border); border-left: 3.5px solid var(--accent); font-size: 12.5px; }
  .reply-banner.show { display: flex; }
  .reply-banner-info { min-width: 0; flex: 1; }
  .reply-banner-info strong { color: var(--accent); display: block; font-size: 11.5px; margin-bottom: 1px; }
  .reply-banner-info span { color: var(--text-sub); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .composer-wrap { padding: 12px 18px 14px; background: var(--bg-sidebar); border-top: 1px solid var(--border); position: relative; }
  .composer-pill { display: flex; align-items: flex-end; gap: 6px; background: var(--bg-surface); border: 1.5px solid transparent; border-radius: 24px; padding: 5px 6px 5px 8px; transition: border-color 0.15s, background 0.15s, box-shadow 0.15s; }
  .composer-pill:focus-within { background: var(--bg-sidebar); border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .composer-pill textarea { flex: 1; resize: none; border: none; background: transparent; color: var(--text-main); padding: 8px 6px; font-family: inherit; font-size: 14px; line-height: 1.42; max-height: 115px; outline: none; }
  .composer-pill textarea:disabled { opacity: 0.55; cursor: not-allowed; }
  .send-btn { border: none; background: var(--accent-grad); color: #fff; width: 38px; height: 38px; border-radius: 50%; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; transition: transform 0.12s, opacity 0.15s; box-shadow: 0 3px 10px rgba(0, 104, 255, 0.28); }
  .send-btn svg { width: 18px; height: 18px; transform: translateX(1px); }
  .send-btn:hover { opacity: 0.94; transform: scale(1.05); }
  .send-btn:active { transform: scale(0.95); }
  .send-btn:disabled { opacity: 0.35; cursor: not-allowed; box-shadow: none; transform: none; }
  .emoji-popover { position: absolute; bottom: 72px; left: 18px; background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: 16px; padding: 10px; box-shadow: var(--shadow-md); display: none; grid-template-columns: repeat(7, 1fr); gap: 4px; z-index: 15; }
  .emoji-popover.open { display: grid; }
  .emoji-btn { border: none; background: transparent; font-size: 20px; padding: 6px; border-radius: 10px; cursor: pointer; transition: background 0.12s, transform 0.1s; }
  .emoji-btn:hover { background: var(--bg-surface); transform: scale(1.15); }
  .drop-overlay { position: absolute; inset: 14px; background: var(--accent-soft); border: 2.5px dashed var(--accent); border-radius: 22px; display: none; align-items: center; justify-content: center; z-index: 25; backdrop-filter: blur(4px); pointer-events: none; }
  .drop-overlay.show { display: flex; }
  .drop-box { background: var(--bg-sidebar); padding: 22px 32px; border-radius: 18px; box-shadow: var(--shadow-md); font-weight: 700; color: var(--accent); font-size: 15px; display: flex; align-items: center; gap: 10px; }
  .right-drawer { width: 390px; background: var(--bg-sidebar); border-left: 1px solid var(--border); display: none; flex-direction: column; flex-shrink: 0; z-index: 4; }
  .right-drawer.open { display: flex; }
  .drawer-header { height: 68px; padding: 0 14px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .drawer-tabs { display: flex; gap: 4px; background: var(--bg-surface); padding: 4px; border-radius: 11px; flex: 1; }
  .drawer-tab { flex: 1; border: none; background: transparent; color: var(--text-sub); font-size: 12.5px; font-weight: 700; padding: 6px 8px; border-radius: 8px; cursor: pointer; transition: all 0.15s; }
  .drawer-tab.active { background: var(--bg-sidebar); color: var(--text-main); box-shadow: var(--shadow-xs); }
  .drawer-pane { flex: 1; overflow-y: auto; display: none; flex-direction: column; }
  .drawer-pane.active { display: flex; }
  .info-profile { padding: 22px 16px 18px; text-align: center; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; }
  .info-profile h3 { font-size: 16px; font-weight: 800; margin-top: 10px; }
  .info-profile p { font-size: 12px; color: var(--text-sub); margin-top: 3px; }
  .drawer-sec { padding: 14px 16px; border-bottom: 1px solid var(--border); }
  .drawer-sec-title { font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-sub); margin-bottom: 10px; display: flex; justify-content: space-between; }
  .media-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .media-thumb { aspect-ratio: 1; border-radius: 10px; overflow: hidden; background: var(--bg-surface); cursor: zoom-in; border: 1px solid var(--border); }
  .media-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.2s; }
  .media-thumb:hover img { transform: scale(1.07); }
  .shared-file-row { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 10px; text-decoration: none; color: var(--text-main); transition: background 0.14s; }
  .shared-file-row:hover { background: var(--bg-surface); }
  .shared-file-row .file-ext { width: 34px; height: 34px; font-size: 9.5px; border-radius: 9px; }
  .shared-empty { font-size: 12.5px; color: var(--text-muted); text-align: center; padding: 14px 6px; }
  .term-pane-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0a0f1d; color: #e2e8f0; }
  .term-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 9px 12px; border-bottom: 1px solid #1e293b; background: #0f172a; }
  .log-filters { display: flex; gap: 5px; flex-wrap: wrap; }
  .log-filter-btn { border: 1px solid #1e293b; background: #111827; color: #94a3b8; font-size: 11px; font-weight: 700; padding: 4px 9px; border-radius: 999px; cursor: pointer; transition: all 0.14s; }
  .log-filter-btn:hover { color: #e2e8f0; border-color: #334155; }
  .log-filter-btn.active { background: #1d4ed8; border-color: #2563eb; color: #fff; }
  .term-clear-btn { border: 1px solid #334155; background: transparent; color: #94a3b8; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 8px; cursor: pointer; flex-shrink: 0; }
  .term-clear-btn:hover { color: #f8fafc; background: #1e293b; }
  .term-body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px; font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace; font-size: 11.8px; line-height: 1.56; }
  .term-banner { color: #64748b; font-size: 11.5px; padding-bottom: 10px; margin-bottom: 10px; border-bottom: 1px dashed #1e293b; line-height: 1.55; }
  .term-banner strong { color: #38bdf8; }
  .log-line { margin-bottom: 5px; word-break: break-word; }
  .log-time { color: #475569; margin-right: 6px; user-select: none; }
  .log-line.ok { color: #4ade80; }
  .log-line.warn { color: #fbbf24; }
  .log-line.err { color: #f87171; }
  .log-line.info { color: #93c5fd; }
  .term-cmd-block { margin: 8px 0; padding: 8px 10px; border-radius: 8px; background: rgba(30, 41, 59, 0.55); border-left: 3px solid #38bdf8; }
  .term-cmd-block.err { border-left-color: #f87171; background: rgba(127, 29, 29, 0.22); }
  .term-cmd-input { color: #38bdf8; font-weight: 700; margin-bottom: 4px; display: flex; justify-content: space-between; gap: 8px; }
  .term-cmd-block.err .term-cmd-input { color: #fca5a5; }
  .term-cmd-output { color: #e2e8f0; white-space: pre-wrap; word-break: break-word; }
  .term-cmd-block.err .term-cmd-output { color: #fecaca; }
  .term-quick-bar { display: flex; gap: 5px; padding: 7px 10px; border-top: 1px solid #1e293b; background: #0d1424; overflow-x: auto; flex-shrink: 0; }
  .term-quick-chip { border: 1px solid #1e293b; background: #111827; color: #93c5fd; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 7px; cursor: pointer; white-space: nowrap; transition: all 0.12s; }
  .term-quick-chip:hover { background: #1e293b; color: #fff; border-color: #3b82f6; }
  .term-prompt-bar { display: flex; align-items: center; gap: 6px; padding: 9px 12px; border-top: 1px solid #1e293b; background: #0f172a; flex-shrink: 0; }
  .term-prompt-label { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; font-weight: 700; color: #4ade80; white-space: nowrap; user-select: none; }
  .term-input { flex: 1; min-width: 0; border: none; background: transparent; color: #f8fafc; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12.5px; outline: none; }
  .term-input::placeholder { color: #475569; }
  .term-run-btn { border: none; background: #1d4ed8; color: #fff; font-size: 11.5px; font-weight: 700; padding: 5px 10px; border-radius: 7px; cursor: pointer; flex-shrink: 0; }
  .term-run-btn:hover { background: #2563eb; }
  .lightbox { position: fixed; inset: 0; background: rgba(2, 6, 23, 0.88); backdrop-filter: blur(6px); display: none; align-items: center; justify-content: center; z-index: 60; padding: 24px; cursor: zoom-out; }
  .lightbox.open { display: flex; }
  .lightbox img { max-width: 92vw; max-height: 90vh; border-radius: 14px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.65); }
  .toast { position: fixed; top: 16px; right: 20px; background: #0f172a; color: #fff; padding: 10px 16px; border-radius: 12px; font-size: 13px; font-weight: 500; box-shadow: var(--shadow-md); opacity: 0; transform: translateY(-10px); pointer-events: none; transition: all 0.2s; z-index: 70; }
  .toast.show { opacity: 1; transform: translateY(0); }
  @media (max-width: 900px) {
  .sidebar { width: 256px; min-width: 230px; }
  .right-drawer { position: fixed; right: 0; top: 0; bottom: 0; box-shadow: var(--shadow-md); }
  }</style>
</head>
<body>
<div class="app-shell">
  <nav class="nav-rail">
    <button class="rail-avatar-btn" id="railAvatarBtn" title="Bấm để đổi Online / Away">
      <div class="avatar" id="meAvatar">
        <span id="meInitial">?</span>
        <span class="status-dot" id="meDot"></span>
      </div>
    </button>

    <div class="rail-group">
      <button class="rail-btn active" id="railChatsBtn" title="Tin nhắn LAN">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
        <span class="rail-badge" id="totalUnreadBadge">0</span>
      </button>

      <button class="rail-btn" id="railMediaBtn" title="Ảnh & tệp đã chia sẻ">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
      </button>

      <button class="rail-btn active" id="railLogBtn" title="Admin Terminal & Socket Log (Ctrl+`)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
      </button>
    </div>

    <div class="rail-spacer"></div>

    <div class="rail-group">
      <button class="rail-btn active" id="soundBtn" title="Âm thanh thông báo: Bật">
        <svg id="soundIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
      </button>

      <button class="rail-btn" id="accentBtn" title="Đổi màu chủ đạo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.5-.75 1.5-1.5 0-.39-.15-.74-.39-1.01-.23-.26-.38-.61-.38-.99 0-.83.67-1.5 1.5-1.5H16c3.31 0 6-2.69 6-6 0-4.96-4.49-9-10-9z"/></svg>
      </button>

      <button class="rail-btn" id="themeBtn" title="Đổi giao diện Sáng / Tối">
        <svg id="themeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>

      <button class="rail-btn" id="quitBtn" title="Thoát chương trình an toàn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      </button>
    </div>
  </nav>

  <div class="accent-popover" id="accentPopover">
    <button class="swatch selected" data-accent="blue" style="background:#0068ff" title="Zalo Blue"></button>
    <button class="swatch" data-accent="violet" style="background:#6366f1" title="Messenger Violet"></button>
    <button class="swatch" data-accent="emerald" style="background:#059669" title="Emerald Green"></button>
    <button class="swatch" data-accent="rose" style="background:#e11d48" title="Rose Red"></button>
  </div>

  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="brand-wrap">
        <div class="brand-title" id="meName">LAN Chat</div>
        <div class="brand-sub" id="mePorts">TCP: - · UDP: -</div>
      </div>
      <button class="status-pill online" id="statusPill" title="Đổi trạng thái Online / Away">
        <span class="dot"></span>
        <span id="statusText">Online</span>
      </button>
    </div>

    <div class="search-box">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input class="search-input" id="searchInput" type="text" placeholder="Tìm theo tên hoặc địa chỉ IP...">
    </div>

    <div class="filter-tabs" id="filterTabs">
      <button class="filter-tab active" data-filter="all">Tất cả</button>
      <button class="filter-tab" data-filter="online">Online (<span id="onlineCountNum">0</span>)</button>
      <button class="filter-tab" data-filter="unread">Chưa đọc</button>
    </div>

    <div class="peer-list" id="peerList"></div>
  </aside>

  <main class="chat-panel" id="chatPanel">
    <div class="drop-overlay" id="dropOverlay">
      <div class="drop-box">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <span>Thả ảnh hoặc tệp vào đây để gửi qua TCP</span>
      </div>
    </div>

    <header class="chat-header" id="chatHeader" style="display:none;">
      <div class="chat-partner-wrap">
        <div class="avatar sm" id="partnerAvatar">
          <span id="partnerInitial">?</span>
          <span class="status-dot" id="partnerDot"></span>
        </div>
        <div>
          <div class="chat-partner-title">
            <span id="partnerName">...</span>
            <span class="ip-chip" id="partnerIpChip"></span>
          </div>
          <div class="chat-partner-sub" id="partnerSub">...</div>
        </div>
      </div>

      <div class="header-actions">
        <button class="icon-btn" id="hdrTermBtn" title="Bật/tắt Admin Terminal (Ctrl+`)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
        </button>
        <button class="icon-btn" id="hdrMediaBtn" title="Thông tin & Media đã chia sẻ">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><line x1="15" y1="3" x2="15" y2="21"/></svg>
        </button>
        <button class="icon-btn danger" id="hdrDeleteChatBtn" title="Xóa đoạn chat này">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
        </button>
        <button class="btn-reconnect" id="hdrReconnectBtn" style="display:none;" title="Kết nối lại phiên TCP">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          <span>Kết nối lại</span>
        </button>
        <button class="btn-leave" id="leaveBtn" title="Gửi gói BYE và đóng phiên chat">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          <span>Rời chat</span>
        </button>
      </div>
    </header>

    <section class="messages-area" id="messagesArea">
      <div class="welcome-state">
        <div class="welcome-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
        </div>
        <h2>P2P LAN Chat &amp; File Sharing</h2>
        <p>Chọn một thiết bị bên trái để nhắn tin, hoặc dùng bảng <b>Admin Terminal</b> bên phải để quản trị bằng lệnh <b>/list</b>, <b>/chat</b>, <b>/send</b>, <b>/status</b>.</p>
        <div class="feature-chips">
          <span class="feature-chip">Persistent Peer ID</span>
          <span class="feature-chip">Admin Terminal</span>
          <span class="feature-chip">UDP Room Isolation</span>
          <span class="feature-chip">SHA-256 &amp; Speed</span>
          <span class="feature-chip">Đã xem &amp; React</span>
        </div>
      </div>
    </section>

    <button class="scroll-fab" id="scrollFab" title="Cuộn xuống tin mới nhất">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
    </button>

    <div class="reply-banner" id="replyBanner">
      <div class="reply-banner-info">
        <strong id="replyBannerTitle">Đang trả lời...</strong>
        <span id="replyBannerSnippet">...</span>
      </div>
      <button class="icon-btn" id="cancelReplyBtn" title="Hủy trả lời" style="width:28px;height:28px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>

    <div class="disconnected-banner" id="disconnectedBanner">
      <div class="disconnected-info">
        <span class="disconnected-dot"></span>
        <div>
          <div class="disconnected-text" id="disconnectedTitle">Phiên trò chuyện đã ngắt kết nối</div>
          <div class="disconnected-sub" id="disconnectedSub">Bấm Kết nối lại để mở lại kênh TCP và tiếp tục nhắn tin</div>
        </div>
      </div>
      <button class="btn-reconnect" id="bannerReconnectBtn" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        <span>Kết nối lại</span>
      </button>
    </div>

    <footer class="composer-wrap" id="composerWrap">
      <div class="emoji-popover" id="emojiPopover"></div>
      <div class="composer-pill">
        <input type="file" id="imageInput" accept="image/*" multiple hidden>
        <input type="file" id="fileInput" multiple hidden>

        <button class="icon-btn" id="emojiBtn" title="Biểu tượng cảm xúc" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>
        </button>

        <button class="icon-btn" id="pickImageBtn" title="Gửi ảnh" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
        </button>

        <button class="icon-btn" id="pickFileBtn" title="Đính kèm tệp tin" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
        </button>

        <textarea id="msgInput" rows="1" placeholder="Chọn người dùng để bắt đầu trò chuyện..." disabled></textarea>

        <button class="send-btn" id="sendBtn" title="Gửi tin nhắn (Enter)" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>
    </footer>
  </main>

  <aside class="right-drawer open" id="rightDrawer">
    <div class="drawer-header">
      <div class="drawer-tabs">
        <button class="drawer-tab active" data-pane="logs">&gt;_ Terminal</button>
        <button class="drawer-tab" data-pane="media">Ảnh &amp; Tệp</button>
      </div>
      <button class="icon-btn" id="closeDrawerBtn" title="Đóng bảng phụ (Ctrl+`)" style="width:30px;height:30px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>

    <div class="drawer-pane active" id="paneLogs">
      <div class="term-pane-wrap">
        <div class="term-toolbar">
          <div class="log-filters" id="logFilters">
            <button class="log-filter-btn active" data-lfilter="all">Tất cả</button>
            <button class="log-filter-btn" data-lfilter="cmd">Lệnh</button>
            <button class="log-filter-btn" data-lfilter="udp">UDP</button>
            <button class="log-filter-btn" data-lfilter="tcp">TCP</button>
          </div>
          <button class="term-clear-btn" id="termClearBtn" type="button" title="Xóa màn hình terminal (/clear)">Xóa</button>
        </div>

        <div class="term-body" id="termBody"></div>

        <div class="term-quick-bar" id="termQuickBar">
          <button class="term-quick-chip" type="button" data-qcmd="/list" data-autorun="1">/list</button>
          <button class="term-quick-chip" type="button" data-qcmd="/chat " data-autorun="0">/chat</button>
          <button class="term-quick-chip" type="button" data-qcmd="/send " data-autorun="0">/send</button>
          <button class="term-quick-chip" type="button" data-qcmd="/status away" data-autorun="1">/status away</button>
          <button class="term-quick-chip" type="button" data-qcmd="/status online" data-autorun="1">/status online</button>
          <button class="term-quick-chip" type="button" data-qcmd="/leave" data-autorun="1">/leave</button>
          <button class="term-quick-chip" type="button" data-qcmd="/reconnect" data-autorun="1">/reconnect</button>
          <button class="term-quick-chip" type="button" data-qcmd="/help" data-autorun="1">/help</button>
        </div>

        <div class="term-prompt-bar">
          <span class="term-prompt-label" id="termPromptLabel">&gt;</span>
          <input class="term-input" id="termInput" type="text" autocomplete="off" spellcheck="false" placeholder="Gõ /list, /chat <tên|số>, /send <file>, /help... (↑↓ lịch sử, Tab gợi ý)">
          <button class="term-run-btn" id="termRunBtn" type="button">Chạy</button>
        </div>
      </div>
    </div>

    <div class="drawer-pane" id="paneMedia">
      <div class="info-profile" id="drawerProfile">
        <div class="avatar lg" id="drawerAvatar">?</div>
        <h3 id="drawerPartnerName">Chưa chọn</h3>
        <p id="drawerPartnerMeta">Chọn cuộc trò chuyện để xem ảnh &amp; tệp đã chia sẻ</p>
      </div>
      <div class="drawer-sec">
        <div class="drawer-sec-title"><span>Ảnh đã chia sẻ</span><span id="sharedImgCount">0</span></div>
        <div id="sharedImagesContainer"></div>
      </div>
      <div class="drawer-sec" style="border-bottom:none;">
        <div class="drawer-sec-title"><span>Tệp đã chia sẻ</span><span id="sharedFileCount">0</span></div>
        <div id="sharedFilesContainer"></div>
      </div>
    </div>
  </aside>
</div>

<div class="lightbox" id="lightbox"><img id="lightboxImg" src="" alt="Preview"></div>
<div class="toast" id="toast"></div>

<script>
const EMOJIS = [
  "😀","😂","🤣","😍","🥰","😎","🤔","😭","😤","🥳","🙏","👍","👎","👏",
  "❤️","🔥","✨","🎉","💯","✅","⚡","🚀","💻","📎","📷","☕","🎯","🤝"
];
const QUICK_REACTS = ["❤️","😂","😮","😢","👍","🔥"];
const AVATAR_COLORS = [
  "linear-gradient(135deg,#0084ff,#005ce6)",
  "linear-gradient(135deg,#10b981,#047857)",
  "linear-gradient(135deg,#8b5cf6,#6d28d9)",
  "linear-gradient(135deg,#f59e0b,#d97706)",
  "linear-gradient(135deg,#ec4899,#be185d)",
  "linear-gradient(135deg,#06b6d4,#0284c7)"
];

const SVG_REPLY = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>`;
const SVG_TRASH = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>`;
const SVG_DL = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
const SVG_RETRY = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;
const SVG_SUN = `<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>`;
const SVG_MOON = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>`;
const SVG_VOL_ON = `<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>`;
const SVG_VOL_OFF = `<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>`;

const TERM_COMMANDS = ["/list", "/chat ", "/send ", "/transfers", "/cancel ", "/leave", "/reconnect", "/status ", "/delete", "/help", "/clear", "/quit"];
const $ = id => document.getElementById(id);
const on = (id, ev, fn) => $(id).addEventListener(ev, fn);
const WELCOME_HTML = $("messagesArea").innerHTML;
let appState = null;
let lastPeerSig = "";
let lastRenderedPartner = null;
let lastMsgSignature = "";
let lastTermSig = "";
let termHistory = [];
let termHistoryIdx = -1;
let knownMsgIds = new Set();
let lastTotalUnread = 0;
let peerFilter = "all";
let logFilter = "all";
let searchQuery = "";
let toastTimer = null;
let replyingTo = null;
let typingSentAt = 0;
let typingIdleTimer = null;
let soundEnabled = localStorage.getItem("lan_chat_sound") !== "off";
let audioCtx = null;

function colorFor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function formatSize(bytes) {
  let s = Number(bytes) || 0;
  const units = ["B","KB","MB","GB"];
  let u = 0;
  while (s >= 1024 && u < units.length - 1) { s /= 1024; u++; }
  return u === 0 ? `${Math.round(s)} B` : `${s.toFixed(1)} ${units[u]}`;
}

function formatTransferPair(doneBytes, totalBytes) {
  const total = Math.max(Number(totalBytes) || 0, 0);
  const done = Math.min(Math.max(Number(doneBytes) || 0, 0), total || Number(doneBytes) || 0);
  const units = ["B", "KB", "MB", "GB"];
  let u = 0;
  let div = 1;
  while (total / div >= 1024 && u < units.length - 1) {
    div *= 1024;
    u++;
  }
  if (u === 0) return `${Math.round(done)} / ${Math.round(total)} B`;
  const dStr = (done / div).toFixed(2);
  const tStr = (total / div).toFixed(2);
  return `${dStr} / ${tStr} ${units[u]}`;
}

function extOf(name) {
  const parts = (name || "").split(".");
  return parts.length > 1 ? parts.pop().slice(0, 4).toUpperCase() : "FILE";
}

function extClass(ext) {
  const e = ext.toLowerCase();
  if (["pdf"].includes(e)) return "pdf";
  if (["zip","rar","7z","tar","gz"].includes(e)) return "zip";
  if (["py","js","ts","cpp","c","h","java","html","css","json","tex"].includes(e)) return "code";
  if (["mp4","mp3","mov","wav","mkv"].includes(e)) return "media";
  return "";
}

function playPing() {
  if (!soundEnabled) return;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    if (!audioCtx) audioCtx = new Ctx();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, audioCtx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(660, audioCtx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.06, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.16);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.16);
  } catch (e) {}
}

function showToast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2500);
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function apiPost(url, bodyObj) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bodyObj || {})
  });
  return res.json();
}

async function refreshState() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    if (!res.ok) return;
    appState = await res.json();
    renderAll();
  } catch (e) {}
}

function renderAll() {
  if (!appState) return;
  const me = appState.me;
  const totalUnread = (appState.peers || []).reduce((acc, p) => acc + (p.unread || 0), 0);
  if (totalUnread > lastTotalUnread) playPing();
  lastTotalUnread = totalUnread;

  document.title = totalUnread > 0 ? `(${totalUnread}) LAN Chat — ${me.name}` : `LAN Chat — ${me.name}`;
  $("meName").innerHTML = `${escapeHtml(me.name)}<span class="id-tag" title="Peer ID: ${escapeHtml(me.peer_id)}">#${escapeHtml(me.short_id || "")}</span>`;
  $("meInitial").textContent = me.name[0].toUpperCase();
  $("meAvatar").style.background = colorFor(me.peer_id || me.name);
  $("mePorts").innerHTML = `<span class="room-badge">#${escapeHtml(me.room || "default")}</span> · TCP ${me.tcp_port} · UDP ${me.udp_port}`;

  $("meDot").className = "status-dot " + (me.status === "away" ? "away" : "");
  $("statusPill").className = "status-pill " + me.status;
  $("statusText").textContent = me.status === "online" ? "Online" : "Away";

  const badge = $("totalUnreadBadge");
  badge.textContent = totalUnread > 99 ? "99+" : String(totalUnread);
  badge.classList.toggle("show", totalUnread > 0);

  renderPeers();
  renderChat();
  renderSharedMedia();
  renderLogs();
}

function renderPeers() {
  const peers = appState.peers || [];
  const onlineNum = peers.filter(p => p.online).length;
  $("onlineCountNum").textContent = String(onlineNum);

  const q = searchQuery.trim().toLowerCase();
  const filtered = peers.filter(p => {
    if (peerFilter === "online" && !p.online) return false;
    if (peerFilter === "unread" && !(p.unread > 0)) return false;
    if (
      q &&
      !p.name.toLowerCase().includes(q) &&
      !(p.ip || "").includes(q) &&
      !(p.peer_id || "").toLowerCase().includes(q)
    ) return false;
    return true;
  });

  const sig = JSON.stringify([appState.current_partner, peerFilter, q, filtered]);
  if (sig === lastPeerSig) return;
  lastPeerSig = sig;

  const listEl = $("peerList");
  if (!filtered.length) {
    listEl.innerHTML = `
      <div class="empty-peers">
        <div class="radar-wrap"><div class="radar-ring"></div><div class="radar-ring"></div><div class="radar-core"></div></div>
        ${peers.length ? "Không có cuộc trò chuyện phù hợp bộ lọc." : "Đang quét phòng <b>#" + escapeHtml(appState.me.room || "default") + "</b>...<br>UDP Broadcast cổng " + appState.me.udp_port}
      </div>`;
    return;
  }

  listEl.innerHTML = filtered.map(p => {
    const pid = p.peer_id;
    const active = pid === appState.current_partner ? "active" : "";
    const unreadCls = p.unread > 0 ? "has-unread" : "";
    const dotCls = !p.online
      ? "offline"
      : (p.session_state === "disconnected" ? "disconnected" : (p.status === "away" ? "away" : ""));
    const subIp = !p.online ? "offline" : (p.status === "away" ? "away" : `${p.ip}:${p.port}`);
    const previewCls = p.typing ? "peer-preview typing" : "peer-preview";
    const preview = p.typing
      ? "đang nhập tin nhắn..."
      : (!p.online
        ? "Đã thoát ứng dụng"
        : (p.session_state === "disconnected"
          ? "Đã ngắt kết nối chat · Bấm Kết nối lại"
          : (p.last_preview || (p.status === "away" ? "Đang vắng mặt (away)" : "Sẵn sàng trò chuyện"))));
    const badge = p.unread > 0 ? `<span class="unread-badge">${p.unread}</span>` : "";
    const idTag = p.is_duplicate_name
      ? `<span class="id-tag" title="Peer ID: ${escapeHtml(pid)}">#${escapeHtml(p.short_id || pid.slice(0,4))}</span>`
      : "";
    const delBtn = (!p.online || p.last_preview)
      ? `<button class="peer-del-btn" type="button" title="Xóa đoạn chat" data-del-peer="${escapeHtml(pid)}" data-del-name="${escapeHtml(p.name)}">${SVG_TRASH}</button>`
      : "";
    return `
      <div class="peer-item ${active} ${unreadCls}" data-peer="${escapeHtml(pid)}">
        <div class="avatar sm" style="background:${colorFor(pid)}">
          ${escapeHtml(p.name[0].toUpperCase())}
          <span class="status-dot ${dotCls}"></span>
        </div>
        <div class="peer-info">
          <div class="peer-top">
            <span class="peer-name">${escapeHtml(p.name)}${idTag}</span>
            <span class="peer-ip">${escapeHtml(subIp)}</span>
          </div>
          <div class="peer-bottom">
            <div class="${previewCls}">${escapeHtml(preview)}</div>
            ${badge}
          </div>
        </div>
        ${delBtn}
      </div>`;
  }).join("");

  listEl.querySelectorAll(".peer-item").forEach(el => {
    el.addEventListener("click", () => selectPeer(el.dataset.peer));
  });
  listEl.querySelectorAll(".peer-del-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      deleteConversation(btn.dataset.delPeer, btn.dataset.delName);
    });
  });
}

function renderChat() {
  const partner = appState.current_partner;
  const headerEl = $("chatHeader");
  const area = $("messagesArea");
  const input = $("msgInput");
  const sendBtn = $("sendBtn");
  const pickImg = $("pickImageBtn");
  const pickFile = $("pickFileBtn");
  const emojiBtn = $("emojiBtn");

  const discBanner = $("disconnectedBanner");
  const composerWrap = $("composerWrap");
  const leaveBtn = $("leaveBtn");
  const hdrReconnectBtn = $("hdrReconnectBtn");
  const bannerReconnectBtn = $("bannerReconnectBtn");

  if (!partner) {
    headerEl.style.display = "none";
    discBanner.classList.remove("show");
    composerWrap.style.display = "block";
    clearReply();
    input.disabled = true;
    input.placeholder = "Chọn người dùng ở danh sách bên trái để nhắn tin...";
    sendBtn.disabled = true;
    pickImg.disabled = true;
    pickFile.disabled = true;
    emojiBtn.disabled = true;

    if (lastRenderedPartner !== null) {
      lastRenderedPartner = null;
      lastMsgSignature = "";
      knownMsgIds.clear();
      area.innerHTML = WELCOME_HTML;
    }
    return;
  }

  const peerInfo = (appState.peers || []).find(p => p.peer_id === partner);
  const partnerDisplayName = peerInfo ? peerInfo.name : partner.slice(0, 4);
  const partnerShortId = peerInfo ? (peerInfo.short_id || partner.slice(0, 4)) : partner.slice(0, 4);
  const isOnline = !!(peerInfo && peerInfo.online);
  const isAway = !!(peerInfo && peerInfo.status === "away");
  const canReconnect = !!(peerInfo && (peerInfo.online || peerInfo.can_reconnect));
  const isConnectedTcp = (appState.partner_session_state === "connected");
  const isDisconnected = (appState.partner_session_state === "disconnected");
  const canInteract = !isDisconnected && (isOnline || isConnectedTcp);

  headerEl.style.display = "flex";
  $("partnerInitial").textContent = partnerDisplayName[0].toUpperCase();
  $("partnerAvatar").style.background = colorFor(partner);
  $("partnerName").innerHTML = `${escapeHtml(partnerDisplayName)}<span class="id-tag" title="Peer ID: ${escapeHtml(partner)}">#${escapeHtml(partnerShortId)}</span>`;

  const ipChip = $("partnerIpChip");
  ipChip.textContent = (isOnline || isConnectedTcp) && peerInfo && peerInfo.ip ? `${peerInfo.ip}:${peerInfo.port}` : "offline";

  const pDot = $("partnerDot");
  const pSub = $("partnerSub");
  if (isDisconnected) {
    pDot.className = isOnline ? "status-dot disconnected" : "status-dot offline";
    pSub.className = "chat-partner-sub";
    pSub.textContent = isOnline
      ? "Đã ngắt kết nối chat (app vẫn mở) · Bấm Kết nối lại"
      : (canReconnect ? "Mất kết nối · Bấm Kết nối lại để thử mở lại kênh TCP" : "Đã thoát ứng dụng");
  } else if (!isOnline && !isConnectedTcp) {
    pDot.className = "status-dot offline";
    pSub.className = "chat-partner-sub";
    pSub.textContent = "Đã ngoại tuyến (offline)";
  } else if (appState.partner_typing) {
    pDot.className = isAway ? "status-dot away" : "status-dot";
    pSub.className = "chat-partner-sub typing";
    pSub.textContent = `${partnerDisplayName} đang nhập tin nhắn...`;
  } else if (isAway) {
    pDot.className = "status-dot away";
    pSub.className = "chat-partner-sub";
    pSub.textContent = "Đang vắng mặt (away) · Vẫn có thể nhắn tin";

  } else {
    pDot.className = "status-dot";
    pSub.className = "chat-partner-sub";
    pSub.textContent = "Đang hoạt động";
  }

  if (isDisconnected) {
    leaveBtn.style.display = "none";
    hdrReconnectBtn.style.display = "inline-flex";
    hdrReconnectBtn.disabled = !canReconnect;
    discBanner.classList.add("show");
    bannerReconnectBtn.disabled = !canReconnect;
    $("disconnectedTitle").textContent = isOnline
      ? `Phiên chat với ${partnerDisplayName} (#${partnerShortId}) đã ngắt kết nối`
      : (canReconnect
        ? `Mất kết nối với ${partnerDisplayName} (#${partnerShortId})`
        : `${partnerDisplayName} (#${partnerShortId}) đã thoát ứng dụng`);
    $("disconnectedSub").textContent = canReconnect
      ? "Nhấn Kết nối lại để mở lại kênh TCP trực tiếp"
      : "Chờ thiết bị mở lại ứng dụng và trực tuyến để kết nối lại";
    composerWrap.style.display = "none";
    clearReply();
  } else {
    leaveBtn.style.display = "inline-flex";
    hdrReconnectBtn.style.display = "none";
    discBanner.classList.remove("show");
    composerWrap.style.display = "block";
  }

  input.disabled = !canInteract;
  input.placeholder = canInteract
    ? `Nhắn tin tới ${partnerDisplayName}... (Enter gửi · Ctrl+V dán ảnh · Kéo thả tệp)`
    : `${partnerDisplayName} hiện đang ngoại tuyến...`;
  sendBtn.disabled = !canInteract;
  pickImg.disabled = !canInteract;
  pickFile.disabled = !canInteract;
  emojiBtn.disabled = !canInteract;

  const msgs = appState.messages || [];
  let lastOutId = null;
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].direction === "out") { lastOutId = msgs[i].id; break; }
  }

  for (const m of msgs) {
    if (
      m.direction === "out" &&
      (m.kind === "file" || m.kind === "image") &&
      (m.transfer_status === "failed" || m.transfer_status === "cancelled")
    ) {
      abortActiveUploadById(m.id);
    }
  }

  const sig = partner + "::" + (appState.partner_session_state || "") + "::" + (isAway ? "A" : "O") + "::" + (appState.partner_typing ? "T" : "F") + "::" + JSON.stringify(msgs.map(m => [
    m.id, m.transfer_status, m.file_path, m.status, m.error, m.seen_at, m.recalled, m.reactions, m.can_server_retry
  ]));
  if (sig === lastMsgSignature) {
    patchLiveFileProgress(msgs);
    return;
  }

  const nearBottom = (area.scrollHeight - area.scrollTop - area.clientHeight) < 130;
  const switched = lastRenderedPartner !== partner;
  if (switched) {
    clearReply();
    knownMsgIds.clear();
  }
  lastRenderedPartner = partner;
  lastMsgSignature = sig;

  if (!switched) {
    for (const m of msgs) {
      if (!knownMsgIds.has(m.id) && m.direction === "in") {
        playPing();
        break;
      }
    }
  }

  if (!msgs.length && !(appState.partner_typing && isOnline)) {
    area.innerHTML = `<div class="msg-row sys"><div class="bubble">Bắt đầu cuộc trò chuyện P2P với ${escapeHtml(partnerDisplayName)} (#${escapeHtml(partnerShortId)})</div></div>`;
    return;
  }

  const htmlParts = [];
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i];
    const prev = i > 0 ? msgs[i - 1] : null;
    const next = i < msgs.length - 1 ? msgs[i + 1] : null;

    const isSpecial = (x) => !x || x.kind === "system" || x.kind === "divider";
    const sameAsPrev = !isSpecial(prev) && !isSpecial(m) && prev.direction === m.direction && prev.sender_id === m.sender_id;
    const sameAsNext = !isSpecial(next) && !isSpecial(m) && next.direction === m.direction && next.sender_id === m.sender_id;
    const isNew = !switched && !knownMsgIds.has(m.id);

    htmlParts.push(renderMessageHtml(m, {
      isLastOut: m.id === lastOutId,
      sameAsPrev,
      sameAsNext,
      isNew
    }));
  }

  if (appState.partner_typing && canInteract) {
    htmlParts.push(`
      <div class="typing-row">
        <div class="avatar xs" style="background:${colorFor(partner)}">${escapeHtml(partnerDisplayName[0].toUpperCase())}</div>
        <div class="typing-bubble"><span></span><span></span><span></span></div>
      </div>`);
  }

  msgs.forEach(m => knownMsgIds.add(m.id));
  area.innerHTML = htmlParts.join("");

  area.querySelectorAll("img.previewable").forEach(img => {
    img.addEventListener("click", () => openLightbox(img.src));
  });
  area.querySelectorAll("[data-react-id]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); toggleReaction(btn.dataset.reactId, btn.dataset.emoji); });
  });
  area.querySelectorAll("[data-reply-id]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); startReply(btn.dataset.replyId); });
  });
  area.querySelectorAll("[data-recall-id]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); recallMsg(btn.dataset.recallId); });
  });
  area.querySelectorAll("[data-jump-id]").forEach(el => {
    el.addEventListener("click", () => jumpToMessage(el.dataset.jumpId));
  });
  area.querySelectorAll("[data-retry-id]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); retryMsg(btn.dataset.retryId); });
  });
  area.querySelectorAll("[data-cancel-transfer]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); cancelFileTransfer(btn.dataset.cancelTransfer); });
  });
  area.querySelectorAll("[data-retry-file]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); retryFileTransfer(btn.dataset.retryFile); });
  });
  if (switched || nearBottom) {
    area.scrollTop = area.scrollHeight;
  }
}

function patchLiveFileProgress(msgs) {
  for (const m of msgs) {
    if ((m.kind !== "file" && m.kind !== "image") || m.transfer_status !== "transferring") continue;
    const row = $("msg-" + m.id);
    if (!row) continue;
    const pct = Number(m.progress || 0);
    const totalBytes = Number(m.file_size || 0);
    const doneBytes = Number(m.transferred_bytes || Math.round((pct / 100) * totalBytes));
    const dir = m.direction === "out" ? "out" : "in";

    const fillEl = row.querySelector("[data-prog-fill]");
    if (fillEl) fillEl.style.width = `${Math.max(pct, 2)}%`;

    const bytesEl = row.querySelector("[data-prog-bytes]");
    if (bytesEl) bytesEl.textContent = formatTransferPair(doneBytes, totalBytes);

    const subEl = row.querySelector("[data-prog-sub]");
    if (subEl) subEl.textContent = `${dir === "out" ? "Đang gửi" : "Đang nhận"} · ${pct}%`;

    const spdEl = row.querySelector("[data-prog-speed]");
    if (spdEl) {
      if (m.speed_str) {
        spdEl.textContent = `⚡ ${m.speed_str}`;
        spdEl.style.display = "inline-flex";
      } else {
        spdEl.style.display = "none";
      }
    }
  }
}

function renderMessageHtml(m, opts) {
  if (m.kind === "divider") {
    const tone = escapeHtml(m.tone || "danger");
    return `<div class="divider-row ${tone}"><span>${escapeHtml(m.text)}</span></div>`;
  }
  if (m.kind === "system") {
    return `<div class="msg-row sys"><div class="bubble">${escapeHtml(m.text)}</div></div>`;
  }

  const dir = m.direction === "out" ? "out" : "in";
  const isRecalled = !!m.recalled;
  const groupedCls = opts.sameAsPrev ? "grouped" : "";
  const animCls = opts.isNew ? "new-anim" : "";

  const senderLabel = (dir === "in" && !opts.sameAsPrev)
    ? `<div class="msg-sender">${escapeHtml(m.sender)}</div>` : "";

  const inAvatarHtml = dir === "in"
    ? `<div class="in-avatar-slot">${!opts.sameAsNext ? `<div class="avatar xs" style="background:${colorFor(m.sender_id || m.sender)}">${escapeHtml((m.sender || "?")[0].toUpperCase())}</div>` : ""}</div>`
    : "";

  let actionsHtml = "";
  const isTransferring = (m.kind === "file" || m.kind === "image") && m.transfer_status === "transferring";
  if (!isRecalled && !isTransferring) {
    const reactBtns = QUICK_REACTS.map(em =>
      `<button class="act-btn" type="button" title="Thả ${em}" data-react-id="${escapeHtml(m.id)}" data-emoji="${em}">${em}</button>`
    ).join("");
    const replyBtn = `<button class="act-btn" type="button" title="Trả lời" data-reply-id="${escapeHtml(m.id)}">${SVG_REPLY}</button>`;
    const recallBtn = dir === "out"
      ? `<button class="act-btn danger" type="button" title="Thu hồi tin nhắn" data-recall-id="${escapeHtml(m.id)}">${SVG_TRASH}</button>`
      : "";
    actionsHtml = `<div class="msg-actions">${reactBtns}<span class="act-sep"></span>${replyBtn}${recallBtn}</div>`;
  }

  let replyQuoteHtml = "";
  if (m.reply_to && !isRecalled) {
    replyQuoteHtml = `
      <div class="reply-quote" data-jump-id="${escapeHtml(m.reply_to.id)}" title="Bấm để xem tin gốc">
        <strong>${escapeHtml(m.reply_to.sender || "Tin nhắn")}</strong>
        <span>${escapeHtml(m.reply_to.text || "")}</span>
      </div>`;
  }

  let contentHtml = "";
  if (isRecalled) {
    contentHtml = `<div class="bubble recalled">Tin nhắn đã được thu hồi</div>`;
  } else if (m.kind === "text") {
    const failCls = (dir === "out" && m.status === "failed") ? "failed-bubble" : "";
    contentHtml = `<div class="bubble ${failCls}">${escapeHtml(m.text)}</div>`;
  } else {
    contentHtml = renderMediaOrFileCard(m);
  }

  let reactionsHtml = "";
  const reacts = m.reactions || {};
  const reactKeys = Object.keys(reacts);
  if (reactKeys.length && !isRecalled) {
    const myPeerId = appState.me.peer_id;
    const pills = reactKeys.map(em => {
      const users = reacts[em] || [];
      if (!users.length) return "";
      const mine = users.some(u => (typeof u === "object" ? u.id === myPeerId : u === myPeerId)) ? "mine" : "";
      const tipNames = users.map(u => (typeof u === "object" ? u.name : u)).join(", ");
      const countHtml = users.length > 1 ? `<span class="react-count">${users.length}</span>` : "";
      return `<button class="react-pill ${mine}" type="button" title="${escapeHtml(tipNames)}" data-react-id="${escapeHtml(m.id)}" data-emoji="${em}">${em}${countHtml}</button>`;
    }).join("");
    if (pills) reactionsHtml = `<div class="reactions-bar">${pills}</div>`;
  }

  let metaHtml = "";
  const isFailedOut = (dir === "out" && m.status === "failed");
  const showMeta = !opts.sameAsNext || opts.isLastOut || isFailedOut;
  if (showMeta) {
    let receiptHtml = "";
    if (dir === "out") {
      if (m.status === "failed") {
        if ((m.kind === "file" || m.kind === "image") && m.transfer_status === "cancelled") {
          receiptHtml = `<span class="receipt failed">Đã hủy</span>`;
        } else {
          const retryBtn = m.kind === "text"
            ? `<button class="retry-btn" type="button" data-retry-id="${escapeHtml(m.id)}">Thử lại</button>`
            : "";
          receiptHtml = `<span class="receipt failed" title="${escapeHtml(m.error || "Lỗi kết nối")}">⚠ Gửi thất bại</span>${retryBtn}`;
        }
      } else if (m.status === "sending") {
        receiptHtml = `<span class="receipt sending">⏳ Đang gửi...</span>`;
      } else if (m.status === "seen") {
        receiptHtml = opts.isLastOut
          ? `<span class="receipt seen">✓✓ Đã xem${m.seen_at ? " lúc " + escapeHtml(m.seen_at) : ""}</span>`
          : `<span class="receipt seen" title="Đã xem">✓✓</span>`;
      } else {
        receiptHtml = opts.isLastOut
          ? `<span class="receipt sent">✓ Đã gửi</span>`
          : `<span class="receipt sent" title="Đã gửi">✓</span>`;
      }
    }
    metaHtml = `<div class="msg-meta"><span>${escapeHtml(m.timestamp || "")}</span>${receiptHtml}</div>`;
  }

  return `
    <div class="msg-row ${dir} ${groupedCls} ${animCls}" id="msg-${escapeHtml(m.id)}">
      ${senderLabel}
      <div class="msg-body-wrap">
        ${inAvatarHtml}
        <div class="bubble-stack">
          ${replyQuoteHtml}
          ${contentHtml}
          ${reactionsHtml}
        </div>
        ${actionsHtml}
      </div>
      ${metaHtml}
    </div>`;
}

function renderLiveSpeedRow(m) {
  if (m.transfer_status !== "transferring") return "";
  const hasSpeed = !!(m.speed_str && m.speed_str.trim());
  const styleAttr = hasSpeed ? "" : ' style="display:none;"';
  return `<div class="hash-row"><span class="speed-chip" data-prog-speed${styleAttr}>⚡ ${escapeHtml(m.speed_str || "")}</span></div>`;
}

function renderMediaOrFileCard(m) {
  const pct = Number(m.progress || 0);
  const st = m.transfer_status || "done";
  const dir = m.direction === "out" ? "out" : "in";
  const totalBytes = Number(m.file_size || 0);
  const doneBytes = st === "done" ? totalBytes : Number(m.transferred_bytes || Math.round((pct / 100) * totalBytes));
  const bytesPair = formatTransferPair(doneBytes, totalBytes);
  const mediaUrl = m.file_path ? `/api/media?path=${encodeURIComponent(m.file_path)}` : "";
  const tid = m.transfer_id || m.id || "";

  if (m.kind === "image" && mediaUrl && st === "done") {
    return `
      <div class="media-card">
        <div class="media-img-wrap">
          <img class="previewable" src="${mediaUrl}" alt="${escapeHtml(m.filename)}">
          <a class="media-dl-fab" href="${mediaUrl}&download=1" title="Tải ảnh xuống">${SVG_DL}</a>
        </div>
        <div class="media-footer">
          <span class="media-name" title="${escapeHtml(m.filename)}">${escapeHtml(m.filename)}</span>
          <span class="media-size">${formatSize(totalBytes)}</span>
        </div>
      </div>`;
  }

  const ext = extOf(m.filename);
  const isTransferring = (st === "transferring");
  const speedHtml = renderLiveSpeedRow(m);

  let statusText = "";
  let errCls = "";
  if (isTransferring) {
    statusText = `${dir === "out" ? "Đang gửi" : "Đang nhận"} · ${pct}%`;
  } else if (st === "done") {
    statusText = `${formatSize(totalBytes)} · Hoàn tất`;
  } else if (st === "cancelled") {
    statusText = m.error || "Đã hủy truyền tệp";
    errCls = "err";
  } else {
    statusText = m.error || "Truyền tệp thất bại";
    errCls = "err";
  }

  const progressRowHtml = isTransferring
    ? `<div class="zalo-prog-row">
         <div class="zalo-prog-track"><div class="zalo-prog-fill" data-prog-fill style="width:${Math.max(pct, 2)}%"></div></div>
         <span class="zalo-prog-bytes" data-prog-bytes>${bytesPair}</span>
         <button class="zalo-cancel-btn" type="button" title="Hủy truyền tệp" data-cancel-transfer="${escapeHtml(tid)}">&times;</button>
       </div>`
    : "";

  const canRetryFile = (dir === "out" && (st === "cancelled" || st === "failed"));
  const retryFileBtn = canRetryFile
    ? `<button class="file-retry-btn" type="button" title="Gửi lại tệp này" data-retry-file="${escapeHtml(tid)}">${SVG_RETRY}<span>Gửi lại</span></button>`
    : "";

  const dlBtn = (st === "done" && mediaUrl)
    ? `<a class="file-dl-btn" href="${mediaUrl}&download=1" title="Tải tệp xuống">${SVG_DL}</a>`
    : "";

  return `
    <div class="file-card">
      <div class="file-ext ${extClass(ext)}">${escapeHtml(ext)}</div>
      <div class="file-meta">
        <div class="file-name" title="${escapeHtml(m.filename)}">${escapeHtml(m.filename)}</div>
        ${progressRowHtml}
        <div class="file-sub ${errCls}" data-prog-sub>${escapeHtml(statusText)}</div>
        ${speedHtml}
      </div>
      ${retryFileBtn || dlBtn}
    </div>`;
}

function renderSharedMedia() {
  const partner = appState.current_partner;
  const av = $("drawerAvatar");
  const nameEl = $("drawerPartnerName");
  const metaEl = $("drawerPartnerMeta");
  const imgBox = $("sharedImagesContainer");
  const fileBox = $("sharedFilesContainer");

  if (!partner) {
    av.textContent = "?";
    av.style.background = "var(--accent-grad)";
    nameEl.textContent = "Chưa chọn cuộc trò chuyện";
    metaEl.textContent = "Chọn một người dùng để xem kho ảnh & tệp";
    $("sharedImgCount").textContent = "0";
    $("sharedFileCount").textContent = "0";
    imgBox.innerHTML = `<div class="shared-empty">Chưa có ảnh nào</div>`;
    fileBox.innerHTML = `<div class="shared-empty">Chưa có tệp nào</div>`;
    return;
  }

  const peer = (appState.peers || []).find(p => p.peer_id === partner);
  const pName = peer ? peer.name : partner.slice(0, 4);
  av.textContent = pName[0].toUpperCase();
  av.style.background = colorFor(partner);
  nameEl.innerHTML = `${escapeHtml(pName)}<span class="id-tag">#${escapeHtml(partner.slice(0, 4))}</span>`;
  metaEl.textContent = peer && peer.online ? `ID: ${partner} · ${peer.ip}:${peer.port} · ${peer.status}` : `ID: ${partner} · Ngoại tuyến`;

  const msgs = appState.messages || [];
  const imgs = msgs.filter(m => m.kind === "image" && m.file_path && !m.recalled && m.transfer_status !== "failed");
  const files = msgs.filter(m => m.kind === "file" && !m.recalled && m.transfer_status === "done");

  $("sharedImgCount").textContent = String(imgs.length);
  $("sharedFileCount").textContent = String(files.length);

  if (!imgs.length) {
    imgBox.innerHTML = `<div class="shared-empty">Chưa có ảnh chia sẻ</div>`;
  } else {
    imgBox.innerHTML = `<div class="media-grid">${imgs.slice().reverse().map(m => {
      const url = `/api/media?path=${encodeURIComponent(m.file_path)}`;
      return `<div class="media-thumb"><img class="previewable" src="${url}" alt="${escapeHtml(m.filename)}"></div>`;
    }).join("")}</div>`;
    imgBox.querySelectorAll("img.previewable").forEach(img => {
      img.addEventListener("click", () => openLightbox(img.src));
    });
  }

  if (!files.length) {
    fileBox.innerHTML = `<div class="shared-empty">Chưa có tệp chia sẻ</div>`;
  } else {
    fileBox.innerHTML = files.slice().reverse().map(m => {
      const ext = extOf(m.filename);
      if (m.file_path) {
        const url = `/api/media?path=${encodeURIComponent(m.file_path)}&download=1`;
        return `
          <a class="shared-file-row" href="${url}">
            <div class="file-ext ${extClass(ext)}">${escapeHtml(ext)}</div>
            <div class="file-meta">
              <div class="file-name">${escapeHtml(m.filename)}</div>
              <div class="file-sub">${formatSize(m.file_size)} · ${escapeHtml(m.timestamp || "")}</div>
            </div>
          </a>`;
      }
      return `
        <div class="shared-file-row">
          <div class="file-ext ${extClass(ext)}">${escapeHtml(ext)}</div>
          <div class="file-meta">
            <div class="file-name">${escapeHtml(m.filename)}</div>
            <div class="file-sub">${formatSize(m.file_size)} · Đã gửi · ${escapeHtml(m.timestamp || "")}</div>
          </div>
        </div>`;
    }).join("");
  }
}

function renderLogs() {
  const body = $("termBody");
  const promptEl = $("termPromptLabel");
  const me = appState.me;
  const partnerId = appState.current_partner;
  if (partnerId && appState.partner_session_state !== "disconnected") {
    const pObj = (appState.peers || []).find(p => p.peer_id === partnerId);
    const pName = pObj ? pObj.name : partnerId.slice(0, 4);
    promptEl.textContent = `${me.name}→${pName} $`;
  } else {
    promptEl.textContent = `${me.name}@${me.room || "default"} $`;
  }

  const entries = (appState.terminal_entries || []).filter(e => {
    if (logFilter === "all") return true;
    if (logFilter === "cmd") return e.kind === "cmd_ok" || e.kind === "cmd_err";
    if (logFilter === "udp") return e.channel === "udp";
    if (logFilter === "tcp") return e.channel === "tcp";
    return true;
  });

  const sig = logFilter + "::" + JSON.stringify(entries.map(e => [e.id, e.text]));
  if (sig === lastTermSig) return;
  lastTermSig = sig;

  const bannerHtml = `
    <div class="term-banner">
      <strong>Admin Terminal</strong> · ID: #${escapeHtml(me.short_id || "")} · Room: #${escapeHtml(me.room || "default")}<br>
      Gõ <b>/list</b>, <b>/chat &lt;tên|số&gt;</b>, <b>/send &lt;file&gt;</b>, <b>/leave</b>, <b>/reconnect</b>, <b>/status</b>, <b>/help</b>, <b>/clear</b>, <b>/quit</b>
    </div>`;

  const linesHtml = entries.map(e => {
    if (e.kind === "cmd_ok" || e.kind === "cmd_err") {
      const errCls = e.kind === "cmd_err" ? "err" : "";
      return `
        <div class="term-cmd-block ${errCls}">
          <div class="term-cmd-input">
            <span>$ ${escapeHtml(e.command)}</span>
            <span class="log-time">${escapeHtml(e.time)}</span>
          </div>
          <div class="term-cmd-output">${escapeHtml(e.text)}</div>
        </div>`;
    }
    let cls = "";
    if (e.text.startsWith("[+]") || e.text.includes("reconnected")) cls = "ok";
    else if (e.text.startsWith("[!]") || e.text.includes("disconnected")) cls = "err";
    else if (e.text.startsWith("[-]")) cls = "warn";
    else if (e.text.startsWith("[*]")) cls = "info";
    return `<div class="log-line ${cls}"><span class="log-time">${escapeHtml(e.time)}</span>${escapeHtml(e.text)}</div>`;
  }).join("");

  body.innerHTML = bannerHtml + linesHtml;
  body.scrollTop = body.scrollHeight;
}

function startReply(msgId) {
  const m = (appState.messages || []).find(x => x.id === msgId);
  if (!m) return;
  let snippet = m.text || "";
  if (m.kind === "image") snippet = `📷 ${m.filename}`;
  else if (m.kind === "file") snippet = `📎 ${m.filename}`;
  replyingTo = { id: m.id, sender: m.sender, snippet };
  $("replyBannerTitle").textContent = `Đang trả lời ${m.sender}`;
  $("replyBannerSnippet").textContent = snippet;
  $("replyBanner").classList.add("show");
  $("msgInput").focus();
}

function clearReply() {
  replyingTo = null;
  $("replyBanner").classList.remove("show");
}

function jumpToMessage(msgId) {
  const el = $("msg-" + msgId);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("highlight");
  void el.offsetWidth;
  el.classList.add("highlight");
}

async function selectPeer(peerId) {
  const res = await apiPost("/api/select", { partner: peerId });
  if (res && res.error) showToast(res.error);
  await refreshState();
  const inp = $("msgInput");
  if (!inp.disabled) inp.focus();
}

async function deleteConversation(peerId, peerName) {
  if (!peerId) return;
  const label = peerName || peerId.slice(0, 4);
  if (!confirm(`Xóa toàn bộ đoạn chat với ${label}?`)) return;
  const res = await apiPost("/api/delete-chat", { partner: peerId });
  if (res && res.error) {
    showToast(res.error);
  } else {
    showToast(`Đã xóa đoạn chat với ${label}`);
    lastPeerSig = "";
    lastMsgSignature = "";
  }
  await refreshState();
}

async function runTerminalCommand(explicitLine) {
  const inp = $("termInput");
  const line = (explicitLine !== undefined ? explicitLine : inp.value).trim();
  if (!line) return;
  if (explicitLine === undefined) {
    inp.value = "";
  }
  if (!termHistory.length || termHistory[termHistory.length - 1] !== line) {
    termHistory.push(line);
    if (termHistory.length > 60) termHistory.shift();
  }
  termHistoryIdx = termHistory.length;

  try {
    const res = await apiPost("/api/terminal", { command: line });
    if (res.quit) {
      document.body.innerHTML = `<div style="display:flex;height:100vh;align-items:center;justify-content:center;font-family:sans-serif;color:#64748b;background:#0f172a;">[*] Đã thoát chương trình LAN Chat an toàn (/quit). Bạn có thể đóng tab này.</div>`;
      return;
    }
    if (res.error) showToast(res.error);
    else if (res.toast) showToast(res.toast);
  } catch (e) {
    showToast("Không thể thực thi lệnh trên Terminal.");
  }
  await refreshState();
  inp.focus();
}

async function sendMessage() {
  const inp = $("msgInput");
  const text = inp.value.trim();
  if (!text) return;
  const replyId = replyingTo ? replyingTo.id : "";
  inp.value = "";
  inp.style.height = "auto";
  clearReply();
  notifyTyping(false);

  const res = await apiPost("/api/send", { text, reply_to: replyId });
  if (res.error) showToast(res.error);
  await refreshState();
  const area = $("messagesArea");
  area.scrollTop = area.scrollHeight;
}

async function toggleReaction(msgId, emoji) {
  const res = await apiPost("/api/react", { msg_id: msgId, emoji });
  if (res && res.error) showToast(res.error);
  await refreshState();
}

async function recallMsg(msgId) {
  await apiPost("/api/recall", { msg_id: msgId });
  await refreshState();
}

async function retryMsg(msgId) {
  const res = await apiPost("/api/retry", { msg_id: msgId });
  if (res.error) showToast(res.error);
  await refreshState();
}

async function reconnectPartner() {
  if (!appState || !appState.current_partner) return;
  const hBtn = $("hdrReconnectBtn");
  const bBtn = $("bannerReconnectBtn");
  hBtn.disabled = true;
  bBtn.disabled = true;
  try {
    const res = await apiPost("/api/reconnect", { partner: appState.current_partner });
    if (res.error) {
      showToast(res.error);
    } else {
      showToast("Đã kết nối lại thành công!");
    }
  } catch (e) {
    showToast("Lỗi khi kết nối lại.");
  }
  await refreshState();
  const inp = $("msgInput");
  if (!inp.disabled) inp.focus();
}

function notifyTyping(isTyping) {
  if (!appState || !appState.current_partner) return;
  if (isTyping) {
    const now = Date.now();
    if (now - typingSentAt > 1800) {
      typingSentAt = now;
      apiPost("/api/typing", { typing: true }).catch(() => {});
    }
    clearTimeout(typingIdleTimer);
    typingIdleTimer = setTimeout(() => {
      typingSentAt = 0;
      apiPost("/api/typing", { typing: false }).catch(() => {});
    }, 2400);
  } else {
    clearTimeout(typingIdleTimer);
    if (typingSentAt > 0) {
      typingSentAt = 0;
      apiPost("/api/typing", { typing: false }).catch(() => {});
    }
  }
}

const activeUploadXhrs = new Map();
const retryableFiles = new Map();
let suppressUploadErrorUntil = 0;

function generateUploadId() {
  const bytes = new Uint8Array(6);
  if (window.crypto && window.crypto.getRandomValues) {
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  }
  return (Math.random().toString(16).slice(2) + Date.now().toString(16)).slice(0, 12);
}

function abortActiveUploadById(transferId) {
  if (!transferId) return;
  const xhr = activeUploadXhrs.get(transferId);
  if (xhr) {
    activeUploadXhrs.delete(transferId);
    suppressUploadErrorUntil = Date.now() + 2500;
    try { xhr.abort(); } catch (e) {}
  }
}

async function cancelFileTransfer(transferId) {
  if (!transferId) return;
  suppressUploadErrorUntil = Date.now() + 2500;
  try {
    const res = await apiPost("/api/cancel-file", { transfer_id: transferId });
    if (res.ok) showToast("Đã hủy truyền tệp");
  } catch (e) {}
  abortActiveUploadById(transferId);
  await refreshState();
}

async function retryFileTransfer(msgId) {
  if (!msgId || !appState || !appState.current_partner) return;
  if (appState.partner_session_state === "disconnected") {
    showToast("Phiên chat đang ngắt kết nối. Hãy bấm Kết nối lại trước.");
    return;
  }

  const saved = retryableFiles.get(msgId);
  if (saved && saved.file) {
    const partner = appState.current_partner;
    retryableFiles.delete(msgId);
    await uploadSingleFile(partner, saved.file, msgId);
    await refreshState();
    return;
  }

  const msgObj = (appState.messages || []).find(m => m.id === msgId);
  if (msgObj && msgObj.can_server_retry) {
    const res = await apiPost("/api/retry-file", { msg_id: msgId });
    if (res.error) showToast(res.error);
    await refreshState();
    return;
  }

  showToast("Vui lòng chọn lại tệp để gửi lại.");
  $("fileInput").click();
}

async function computeFileSha256Hex(file) {
  try {
    if (!file || file.size > 100 * 1024 * 1024 || !window.crypto || !window.crypto.subtle) return "";
    const buf = await file.arrayBuffer();
    const digest = await window.crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
  } catch (e) {
    return "";
  }
}

async function uploadSingleFile(partner, file, replaceMsgId = "") {
  const fileSha256 = await computeFileSha256Hex(file);
  return new Promise(resolve => {
    const uploadId = generateUploadId();
    const xhr = new XMLHttpRequest();
    activeUploadXhrs.set(uploadId, xhr);
    retryableFiles.set(uploadId, { partner, file });

    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      activeUploadXhrs.delete(uploadId);
      resolve();
    };

    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText || "{}");
        if (data.ok) {
          retryableFiles.delete(uploadId);
        } else if (data.error && !data.transfer_id) {
          showToast(data.error);
        }
      } catch (e) {}
      finish();
    };
    xhr.onerror = () => {
      if (Date.now() > suppressUploadErrorUntil) {
        refreshState().then(() => {
          const curMsgs = (appState && appState.messages) || [];
          const hasCard = curMsgs.some(
            m => m.id === uploadId && (m.transfer_status === "failed" || m.transfer_status === "cancelled")
          );
          if (!hasCard) showToast("Không thể gửi tệp: " + file.name);
        });
      }
      finish();
    };
    xhr.onabort = () => finish();

    xhr.open("POST", "/api/upload", true);
    xhr.setRequestHeader("X-Partner", encodeURIComponent(partner));
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("X-Upload-Id", uploadId);
    if (fileSha256) {
      xhr.setRequestHeader("X-File-Sha256", fileSha256);
    }
    if (replaceMsgId) {
      xhr.setRequestHeader("X-Replace-Msg-Id", encodeURIComponent(replaceMsgId));
    }
    xhr.send(file);
  });
}

async function uploadFiles(fileList) {
  if (!appState || !appState.current_partner) {
    showToast("Hãy chọn một người dùng trước khi gửi tệp.");
    return;
  }
  const partner = appState.current_partner;
  for (const file of fileList) {
    await uploadSingleFile(partner, file);
    await refreshState();
  }
}

function openLightbox(src) {
  $("lightboxImg").src = src;
  $("lightbox").classList.add("open");
}

function openDrawerTab(tabName) {
  const drawer = $("rightDrawer");
  const alreadyOpenOnSame = drawer.classList.contains("open") &&
    document.querySelector(`.drawer-tab[data-pane="${tabName}"]`).classList.contains("active");

  if (alreadyOpenOnSame) {
    drawer.classList.remove("open");
    syncDrawerButtons();
    return;
  }

  drawer.classList.add("open");
  document.querySelectorAll(".drawer-tab").forEach(t => t.classList.toggle("active", t.dataset.pane === tabName));
  $("paneMedia").classList.toggle("active", tabName === "media");
  $("paneLogs").classList.toggle("active", tabName === "logs");
  syncDrawerButtons();
}

function syncDrawerButtons() {
  const isOpen = $("rightDrawer").classList.contains("open");
  const isMedia = $("paneMedia").classList.contains("active");
  const isLogs = $("paneLogs").classList.contains("active");
  $("railMediaBtn").classList.toggle("active", isOpen && isMedia);
  $("hdrMediaBtn").classList.toggle("active", isOpen && isMedia);
  $("railLogBtn").classList.toggle("active", isOpen && isLogs);
  const hTerm = $("hdrTermBtn");
  if (hTerm) hTerm.classList.toggle("active", isOpen && isLogs);
}

async function toggleMyStatus() {
  if (!appState) return;
  const next = appState.me.status === "online" ? "away" : "online";
  await apiPost("/api/status", { status: next });
  showToast(`Đã đổi trạng thái sang ${next === "online" ? "Online" : "Away"}`);
  await refreshState();
}

on("statusPill", "click", toggleMyStatus);
on("railAvatarBtn", "click", toggleMyStatus);

on("railMediaBtn", "click", () => openDrawerTab("media"));
on("hdrMediaBtn", "click", () => openDrawerTab("media"));
on("hdrDeleteChatBtn", "click", () => {
  if (!appState || !appState.current_partner) return;
  const p = (appState.peers || []).find(x => x.peer_id === appState.current_partner);
  deleteConversation(appState.current_partner, p ? p.name : appState.current_partner.slice(0, 4));
});
on("railLogBtn", "click", () => openDrawerTab("logs"));
on("hdrTermBtn", "click", () => openDrawerTab("logs"));

const termInput = $("termInput");
on("termRunBtn", "click", () => runTerminalCommand());
on("termClearBtn", "click", async () => {
  await apiPost("/api/terminal/clear", {});
  lastTermSig = "";
  await refreshState();
  termInput.focus();
});
on("termBody", "click", () => {
  if (!window.getSelection || !window.getSelection().toString()) {
    termInput.focus();
  }
});
$("termQuickBar").querySelectorAll(".term-quick-chip").forEach(btn => {
  btn.addEventListener("click", () => {
    const cmd = btn.dataset.qcmd;
    if (btn.dataset.autorun === "1") {
      runTerminalCommand(cmd);
    } else {
      termInput.value = cmd;
      termInput.focus();
    }
  });
});
termInput.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    e.preventDefault();
    runTerminalCommand();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (termHistory.length && termHistoryIdx > 0) {
      termHistoryIdx--;
      termInput.value = termHistory[termHistoryIdx];
    } else if (termHistory.length && termHistoryIdx === termHistory.length) {
      termHistoryIdx = termHistory.length - 1;
      termInput.value = termHistory[termHistoryIdx];
    }
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    if (termHistoryIdx < termHistory.length - 1) {
      termHistoryIdx++;
      termInput.value = termHistory[termHistoryIdx];
    } else {
      termHistoryIdx = termHistory.length;
      termInput.value = "";
    }
  } else if (e.key === "Tab") {
    e.preventDefault();
    const cur = termInput.value.trim().toLowerCase();
    if (cur.startsWith("/")) {
      const match = TERM_COMMANDS.find(c => c.startsWith(cur));
      if (match) termInput.value = match;
    }
  }
});
document.addEventListener("keydown", e => {
  if (e.ctrlKey && e.key === "`") {
    e.preventDefault();
    openDrawerTab("logs");
    if ($("rightDrawer").classList.contains("open")) {
      setTimeout(() => termInput.focus(), 30);
    }
  }
});
on("closeDrawerBtn", "click", () => {
  $("rightDrawer").classList.remove("open");
  syncDrawerButtons();
});
document.querySelectorAll(".drawer-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".drawer-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    $("paneMedia").classList.toggle("active", tab.dataset.pane === "media");
    $("paneLogs").classList.toggle("active", tab.dataset.pane === "logs");
    syncDrawerButtons();
  });
});

$("filterTabs").querySelectorAll(".filter-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    peerFilter = btn.dataset.filter;
    lastPeerSig = "";
    if (appState) renderPeers();
  });
});

$("logFilters").querySelectorAll(".log-filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".log-filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    logFilter = btn.dataset.lfilter;
    if (appState) renderLogs();
  });
});

on("leaveBtn", "click", async () => {
  await apiPost("/api/leave", {});
  showToast("Đã ngắt kết nối phiên chat");
  await refreshState();
});
on("hdrReconnectBtn", "click", reconnectPartner);
on("bannerReconnectBtn", "click", reconnectPartner);

on("quitBtn", "click", async () => {
  if (!confirm("Thoát chương trình LAN Chat?")) return;
  await apiPost("/api/shutdown", {});
  document.body.innerHTML = `<div style="display:flex;height:100vh;align-items:center;justify-content:center;font-family:sans-serif;color:#64748b;background:#0f172a;">[*] Đã thoát chương trình LAN Chat an toàn. Bạn có thể đóng tab này.</div>`;
});

on("searchInput", "input", e => {
  searchQuery = e.target.value;
  lastPeerSig = "";
  if (appState) renderPeers();
});

on("cancelReplyBtn", "click", clearReply);
on("sendBtn", "click", sendMessage);

const messagesArea = $("messagesArea");
const scrollFab = $("scrollFab");
messagesArea.addEventListener("scroll", () => {
  const farUp = (messagesArea.scrollHeight - messagesArea.scrollTop - messagesArea.clientHeight) > 220;
  scrollFab.classList.toggle("show", farUp);
});
scrollFab.addEventListener("click", () => {
  messagesArea.scrollTo({ top: messagesArea.scrollHeight, behavior: "smooth" });
});

const msgInput = $("msgInput");
msgInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  } else if (e.key === "Escape" && replyingTo) {
    clearReply();
  }
});
msgInput.addEventListener("input", () => {
  msgInput.style.height = "auto";
  msgInput.style.height = Math.min(msgInput.scrollHeight, 115) + "px";
  notifyTyping(msgInput.value.trim().length > 0);
});
msgInput.addEventListener("paste", e => {
  if (!appState || appState.partner_session_state === "disconnected") return;
  const items = (e.clipboardData || {}).items || [];
  const files = [];
  for (const it of items) {
    if (it.kind === "file") {
      const f = it.getAsFile();
      if (f) {
        const name = f.name && f.name !== "image.png" ? f.name : `screenshot_${Date.now()}.png`;
        files.push(new File([f], name, { type: f.type }));
      }
    }
  }
  if (files.length) { e.preventDefault(); uploadFiles(files); }
});

on("pickImageBtn", "click", () => $("imageInput").click());
on("pickFileBtn", "click", () => $("fileInput").click());
on("imageInput", "change", e => {
  const files = Array.from(e.target.files || []);
  e.target.value = "";
  if (files.length) uploadFiles(files);
});
on("fileInput", "change", e => {
  const files = Array.from(e.target.files || []);
  e.target.value = "";
  if (files.length) uploadFiles(files);
});

const chatPanel = $("chatPanel");
const dropOverlay = $("dropOverlay");
let dragDepth = 0;
chatPanel.addEventListener("dragenter", e => {
  e.preventDefault(); dragDepth++;
  if (appState && appState.current_partner && appState.partner_session_state !== "disconnected") dropOverlay.classList.add("show");
});
chatPanel.addEventListener("dragleave", e => {
  e.preventDefault(); dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropOverlay.classList.remove("show");
});
chatPanel.addEventListener("dragover", e => e.preventDefault());
chatPanel.addEventListener("drop", e => {
  e.preventDefault(); dragDepth = 0; dropOverlay.classList.remove("show");
  if (appState && appState.partner_session_state === "disconnected") { showToast("Phiên chat đang ngắt kết nối. Hãy bấm Kết nối lại."); return; }
  if (e.dataTransfer.files && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});

const emojiPop = $("emojiPopover");
emojiPop.innerHTML = EMOJIS.map(em => `<button class="emoji-btn" type="button">${em}</button>`).join("");
emojiPop.querySelectorAll(".emoji-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    msgInput.value += btn.textContent;
    msgInput.focus();
    emojiPop.classList.remove("open");
  });
});
on("emojiBtn", "click", e => {
  e.stopPropagation();
  emojiPop.classList.toggle("open");
  $("accentPopover").classList.remove("open");
});

const soundBtn = $("soundBtn");
const soundIcon = $("soundIcon");
function syncSoundUI() {
  soundBtn.classList.toggle("active", soundEnabled);
  soundBtn.title = soundEnabled ? "Âm thanh thông báo: Bật" : "Âm thanh thông báo: Tắt";
  soundIcon.innerHTML = soundEnabled ? SVG_VOL_ON : SVG_VOL_OFF;
}
syncSoundUI();
soundBtn.addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  localStorage.setItem("lan_chat_sound", soundEnabled ? "on" : "off");
  syncSoundUI();
  showToast(soundEnabled ? "Đã bật âm thanh thông báo" : "Đã tắt âm thanh thông báo");
});

const accentPop = $("accentPopover");
function applyAccent(name) {
  if (name === "blue") document.documentElement.removeAttribute("data-accent");
  else document.documentElement.setAttribute("data-accent", name);
  localStorage.setItem("lan_chat_accent", name);
  accentPop.querySelectorAll(".swatch").forEach(s => s.classList.toggle("selected", s.dataset.accent === name));
}
applyAccent(localStorage.getItem("lan_chat_accent") || "blue");
on("accentBtn", "click", e => {
  e.stopPropagation();
  accentPop.classList.toggle("open");
  emojiPop.classList.remove("open");
});
accentPop.querySelectorAll(".swatch").forEach(sw => {
  sw.addEventListener("click", e => {
    e.stopPropagation();
    applyAccent(sw.dataset.accent);
    accentPop.classList.remove("open");
  });
});

const themeBtn = $("themeBtn");
const themeIcon = $("themeIcon");
function applyTheme(isDark) {
  if (isDark) {
    document.documentElement.setAttribute("data-theme", "dark");
    themeIcon.innerHTML = SVG_SUN;
    localStorage.setItem("lan_chat_theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
    themeIcon.innerHTML = SVG_MOON;
    localStorage.setItem("lan_chat_theme", "light");
  }
}
applyTheme(localStorage.getItem("lan_chat_theme") === "dark");
themeBtn.addEventListener("click", () => {
  applyTheme(document.documentElement.getAttribute("data-theme") !== "dark");
});

document.addEventListener("click", () => {
  emojiPop.classList.remove("open");
  accentPop.classList.remove("open");
});

on("lightbox", "click", () => {
  $("lightbox").classList.remove("open");
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && appState && appState.current_partner) {
    apiPost("/api/seen", { partner: appState.current_partner }).catch(() => {});
  }
});

const TAB_ID = "tab_" + Math.random().toString(36).slice(2, 10) + "_" + Date.now().toString(36);
let activeES = null;
let isUnloading = false;

function connectSSE() {
  if (isUnloading) return;
  const es = new EventSource("/api/events?tab=" + encodeURIComponent(TAB_ID));
  activeES = es;
  es.onopen = () => {
    if (!document.hidden && appState && appState.current_partner) {
      apiPost("/api/seen", { partner: appState.current_partner }).catch(() => {});
    }
  };
  es.onmessage = () => refreshState();
  es.onerror = () => {
    es.close();
    if (activeES === es) activeES = null;
    if (!isUnloading) setTimeout(connectSSE, 1500);
  };
}

window.addEventListener("pagehide", () => {
  isUnloading = true;
  if (activeES) {
    try { activeES.close(); } catch (e) {}
    activeES = null;
  }
  if (navigator.sendBeacon) {
    try {
      navigator.sendBeacon("/api/tab-close", JSON.stringify({ tab_id: TAB_ID }));
    } catch (e) {}
  }
});

syncDrawerButtons();
refreshState();
connectSSE();</script>
</body>
</html>
"""

class WebUI:
    is_web_ui: bool = True

    def __init__(self, state, web_port: int = 0, download_dir: str = "downloads", idle_shutdown_sec: float = 7.0):
        self.state = state
        self.web_port = web_port
        self.idle_shutdown_sec = max(float(idle_shutdown_sec), 0.0)
        self.download_dir = os.path.abspath(download_dir)
        os.makedirs(self.download_dir, exist_ok=True)

        self.tcp_service = None
        self.server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self.actual_port: int = 0

        self._client_lock = threading.Lock()
        self._active_clients = set()
        self._ever_had_client = False
        self._shutdown_timer: Optional[threading.Timer] = None

        self._upload_lock = threading.Lock()
        self._seen_uploads = set()
        self._seen_order = []

    def _register_client(self, token: str) -> None:
        reconnected = False
        with self._client_lock:
            self._active_clients.add(token)
            self._ever_had_client = True
            if self._shutdown_timer is not None:
                self._shutdown_timer.cancel()
                self._shutdown_timer = None
                reconnected = True
        self.state.set_ui_connected(True)
        if reconnected:
            print("[*] Web GUI tab reconnected — cancelled auto-shutdown.", flush=True)

    def _unregister_client(self, token: str) -> None:
        started = False
        with self._client_lock:
            if token not in self._active_clients:
                return
            self._active_clients.discard(token)
            if self._ever_had_client and not self._active_clients and self.state.is_running() and self.idle_shutdown_sec > 0:
                if self._shutdown_timer is None:
                    t = threading.Timer(self.idle_shutdown_sec, self._on_idle_timeout)
                    t.daemon = True
                    self._shutdown_timer = t
                    t.start()
                    started = True
        if started:
            self.state.set_ui_connected(False)
            secs = int(self.idle_shutdown_sec) if self.idle_shutdown_sec.is_integer() else self.idle_shutdown_sec
            print(f"[*] All Web GUI tabs closed. Auto-shutdown in {secs}s unless reopened (F5 / Ctrl+Shift+T)...", flush=True)

    def _on_idle_timeout(self) -> None:
        with self._client_lock:
            self._shutdown_timer = None
            if self._active_clients or not self.state.is_running():
                return
        print("[*] No active Web GUI tab — shutting down and sending BYE to peers...", flush=True)
        self.state.stop()

    def show_message(self, line: str) -> None:
        self.state.add_log(line)
        print(line, flush=True)

    def _make_handler(self):
        ui = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                pass

            def _send_json(self, obj: dict, status: int = 200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if self.close_connection:
                    self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def _ok(self, **kw):
                return self._send_json({"ok": True, **kw})

            def _err(self, msg: str, status: int = 400):
                return self._send_json({"error": msg}, status=status)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path

                if path in ("/", "/index.html"):
                    body = HTML_PAGE.encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                elif path == "/api/state":
                    self._send_json(ui.state.get_snapshot())

                elif path == "/api/events":
                    qs = urllib.parse.parse_qs(parsed.query)
                    token = (qs.get("tab", [""])[0] or "").strip() or f"sse_{uuid.uuid4().hex[:10]}"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    ui._register_client(token)
                    ver = ui.state.get_version()
                    try:
                        self.wfile.write(f"data: {ver}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        while ui.state.is_running():
                            new_ver = ui.state.wait_for_change(ver, timeout=1.5)
                            if not ui.state.is_running():
                                break
                            if new_ver != ver:
                                ver = new_ver
                                self.wfile.write(f"data: {ver}\n\n".encode("utf-8"))
                            else:
                                self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    finally:
                        ui._unregister_client(token)

                elif path == "/api/media":
                    qs = urllib.parse.parse_qs(parsed.query)
                    rel = qs.get("path", [""])[0]
                    target = os.path.realpath(os.path.join(ui.download_dir, rel))
                    base = os.path.realpath(ui.download_dir)
                    if not target.startswith(base + os.sep) or not os.path.isfile(target):
                        self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                        return
                    ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(os.path.getsize(target)))
                    if qs.get("download", ["0"])[0] == "1":
                        fname = urllib.parse.quote(os.path.basename(target))
                        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{fname}")
                    self.end_headers()
                    try:
                        with open(target, "rb") as f:
                            while chunk := f.read(65536):
                                self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/api/upload":
                    return self._handle_upload()

                length = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    data = json.loads((self.rfile.read(length) if length > 0 else b"{}").decode("utf-8"))
                except ValueError:
                    return self._err("Invalid JSON")

                pid = ui.state.get_current_partner()
                tcp = ui.tcp_service

                if path == "/api/select":
                    target = data.get("partner")
                    ui.state.set_current_partner(target)
                    if target and tcp and not ui.state.is_session_disconnected(target) and ui.state.get_peer_by_id(target):
                        ok, err = tcp.open_chat(target)
                        if not ok:
                            return self._send_json({"ok": False, "error": err})
                        tcp.notify_seen(target)
                    return self._ok()

                if path == "/api/terminal/clear":
                    ui.state.clear_terminal()
                    return self._ok()

                if path == "/api/terminal":
                    return self._handle_terminal((data.get("command") or "").strip())

                if path == "/api/seen":
                    target = data.get("partner") or pid
                    if target and tcp and not ui.state.is_session_disconnected(target):
                        tcp.notify_seen(target)
                    return self._ok()

                if path == "/api/status":
                    st = data.get("status")
                    if st not in ("online", "away"):
                        return self._err("Status must be online or away")
                    ui.state.set_status(st)
                    if tcp:
                        tcp.broadcast_status_tcp(st)
                    ui.show_message(f"[*] Status changed to '{st}'.")
                    return self._ok()

                if path == "/api/delete-chat":
                    target = (data.get("partner") or pid or "").strip()
                    if not target:
                        return self._err("Chưa chọn đoạn chat để xóa")
                    pname = ui.state.get_peer_name(target)
                    ui.state.delete_conversation(target)
                    ui.show_message(f"[*] Đã xóa đoạn chat với {pname} [#{target[:4]}].")
                    return self._ok()

                if path == "/api/leave":
                    if pid:
                        pname = ui.state.get_peer_name(pid)
                        tcp.close_chat(pid) if tcp else ui.state.set_session_state(pid, "disconnected")
                        ui.show_message(f"──────── Bạn đã rời cuộc trò chuyện với {pname} [#{pid[:4]}] ────────")
                    return self._ok()

                if path == "/api/reconnect":
                    target = (data.get("partner") or pid or "").strip()
                    if not target or not tcp:
                        return self._err("Chưa chọn đối tác để kết nối lại")
                    ok, err = tcp.reconnect(target)
                    return self._send_json({"ok": True} if ok else {"error": err}, status=200 if ok else 400)

                if path == "/api/send":
                    text, rep = (data.get("text") or "").strip(), (data.get("reply_to") or "").strip()
                    if not text:
                        return self._ok()
                    if not pid:
                        return self._err("Chưa chọn đối tác chat")
                    if ui.state.is_session_disconnected(pid):
                        return self._err("Phiên chat đang ngắt kết nối. Hãy bấm Kết nối lại.")
                    mid = ui.state.record_outgoing_message(pid, f"[{ui.state.my_name}#{ui.state.my_peer_id[:4]}] {text}", raw_text=text, reply_to=rep)
                    if tcp:
                        tcp.send_message(pid, text, msg_id=mid, reply_to=rep)
                    return self._send_json({"ok": True, "msg_id": mid})

                if path == "/api/react":
                    mid, emoji = (data.get("msg_id") or "").strip(), (data.get("emoji") or "").strip()
                    if not pid or not mid or not emoji or ui.state.is_session_disconnected(pid):
                        return self._err("Không thể thả cảm xúc lúc này")
                    if ui.state.toggle_reaction(pid, mid, ui.state.my_peer_id, ui.state.my_name, emoji) and tcp:
                        tcp.send_reaction(pid, mid, emoji)
                    return self._ok()

                if path == "/api/typing":
                    if pid and tcp and not ui.state.is_session_disconnected(pid):
                        tcp.send_typing(pid, bool(data.get("typing")))
                    return self._ok()

                if path == "/api/recall":
                    mid = (data.get("msg_id") or "").strip()
                    if not pid or not mid:
                        return self._err("Thiếu msg_id")
                    if ui.state.recall_message(pid, mid, requester_id=ui.state.my_peer_id):
                        if tcp:
                            tcp.send_recall(pid, mid)
                        ui.show_message("[*] You recalled a message.")
                    return self._ok()

                if path == "/api/retry":
                    mid = (data.get("msg_id") or "").strip()
                    retry_data = ui.state.prepare_message_retry(pid, mid) if (pid and mid) else None
                    if not retry_data:
                        return self._err("Không tìm thấy tin nhắn cần gửi lại")
                    if tcp:
                        tcp.send_message(pid, retry_data[0], msg_id=mid, reply_to=retry_data[1])
                    return self._ok()

                if path == "/api/cancel-file":
                    tid = (data.get("transfer_id") or "").strip()
                    if not tid:
                        return self._err("Thiếu transfer_id")
                    return self._send_json({"ok": bool(tcp and tcp.cancel_file_transfer(tid))})

                if path == "/api/retry-file":
                    mid = (data.get("msg_id") or "").strip()
                    if not pid or not mid or not tcp:
                        return self._err("Thiếu thông tin tệp cần gửi lại")
                    ok, err = tcp.retry_file_transfer(pid, mid)
                    return self._send_json({"ok": True} if ok else {"error": err}, status=200 if ok else 400)

                if path == "/api/tab-close":
                    tab_id = (data.get("tab_id") or "").strip()
                    if tab_id:
                        ui._unregister_client(tab_id)
                    return self._ok()

                if path == "/api/shutdown":
                    self._ok()
                    threading.Thread(target=ui.state.stop, daemon=True).start()
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

            def _handle_terminal(self, line: str):
                if not line:
                    return self._ok()
                if not line.startswith("/"):
                    pid = ui.state.get_current_partner()
                    if not pid or ui.state.is_session_disconnected(pid):
                        out = "[!] Chưa chọn đối tác hoặc phiên đang ngắt kết nối (gõ /list, /chat hoặc /reconnect)."
                        ui.state.record_terminal_command(line, out, is_error=True)
                        return self._err(out)
                    mid = ui.state.record_outgoing_message(pid, f"[{ui.state.my_name}#{ui.state.my_peer_id[:4]}] {line}", raw_text=line)
                    if ui.tcp_service:
                        ui.tcp_service.send_message(pid, line, msg_id=mid)
                    ui.state.record_terminal_command(line, f"[*] Đã gửi tin nhắn tới {ui.state.get_peer_name(pid)}.")
                    return self._send_json({"ok": True, "msg_id": mid})

                res = execute_command(ui.state, ui.tcp_service, line, is_cli=False)
                if res["clear"]:
                    ui.state.clear_terminal()
                    return self._ok()
                ui.state.record_terminal_command(line, res["output"], is_error=not res["ok"])
                if res["quit"]:
                    self._send_json({"ok": True, "quit": True})
                    threading.Thread(target=ui.state.stop, daemon=True).start()
                    return
                if not res["ok"]:
                    return self._err(res["toast"] or res["output"].splitlines()[0])
                return self._send_json({"ok": True, "toast": res["toast"]})

            def _handle_upload(self):
                self.close_connection = True
                partner = urllib.parse.unquote(self.headers.get("X-Partner", ""))
                safe_name = sanitize_filename(urllib.parse.unquote(self.headers.get("X-Filename", "unnamed_file")))
                upload_id = urllib.parse.unquote(self.headers.get("X-Upload-Id", "")).strip()
                replace_id = urllib.parse.unquote(self.headers.get("X-Replace-Msg-Id", "")).strip()
                raw_sha = (self.headers.get("X-File-Sha256", "") or "").strip().lower()
                file_sha256 = raw_sha if (len(raw_sha) == 64 and all(c in "0123456789abcdef" for c in raw_sha)) else ""
                length = int(self.headers.get("Content-Length", "0") or 0)

                if upload_id:
                    with ui._upload_lock:
                        if upload_id in ui._seen_uploads:
                            try:
                                self._send_json({"ok": False, "error": "Yêu cầu gửi tệp trùng lặp đã được bỏ qua.", "transfer_id": upload_id}, status=409)
                            except OSError:
                                pass
                            return
                        ui._seen_uploads.add(upload_id)
                        ui._seen_order.append(upload_id)
                        if len(ui._seen_order) > 500:
                            ui._seen_uploads.discard(ui._seen_order.pop(0))

                if not partner or not ui.tcp_service:
                    return self._err("Chưa chọn đối tác nhận tệp")
                if ui.state.is_session_disconnected(partner):
                    return self._err("Phiên chat đang ngắt kết nối. Hãy bấm Kết nối lại.")

                ok, err, tid = ui.tcp_service.stream_file_from_reader(
                    partner, safe_name, length, self.rfile,
                    upload_id=upload_id, replace_msg_id=replace_id, precomputed_sha256=file_sha256,
                )
                try:
                    if ok:
                        self._send_json({"ok": True, "filename": safe_name, "transfer_id": tid})
                    else:
                        self._send_json({"ok": False, "error": err, "transfer_id": tid}, status=400 if not tid else 200)
                except OSError:
                    pass

        return Handler

    def start_server(self, tcp_service=None) -> str:
        self.tcp_service = tcp_service
        self.server = ThreadingHTTPServer(("127.0.0.1", self.web_port), self._make_handler())
        self.server.daemon_threads = True
        self.actual_port = self.server.server_address[1]
        self._server_thread = threading.Thread(target=self.server.serve_forever, name="web-ui-server", daemon=True)
        self._server_thread.start()
        return f"http://127.0.0.1:{self.actual_port}"

    def run_input_loop(self, tcp_service=None, open_browser: bool = True) -> None:
        url = self.start_server(tcp_service)
        self.show_message(f"[*] Web GUI đang chạy tại: {url}")
        self.show_message("[*] Nhấn Ctrl+C trong cửa sổ này (hoặc bấm nút Thoát trên web) để dừng.")
        if open_browser:
            webbrowser.open(url)
        try:
            while self.state.is_running():
                time.sleep(0.3)
        except KeyboardInterrupt:
            self.state.stop()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        with self._client_lock:
            if self._shutdown_timer is not None:
                self._shutdown_timer.cancel()
                self._shutdown_timer = None
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except OSError:
                pass
            self.server = None
