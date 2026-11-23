#!/usr/bin/env python3
"""Draws the README diagrams as animated SVG, in English and Japanese.

    python3 docs/images/src/make_diagrams.py

Writes docs/images/<name>.en.svg and <name>.ja.svg. Standard library only. The animations use
SMIL and CSS, which GitHub shows inside <img>. Every SVG carries its own dark background, so it
reads the same in GitHub's light and dark themes.
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1]

FONT_EN = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
FONT_JA = ("-apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', "
           "'Yu Gothic UI', Meiryo, 'Noto Sans JP', 'Segoe UI', sans-serif")
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

TEXT, MUTED, DIM = "#e8edf3", "#9aa5b4", "#5b6676"
CARD, CARD_LINE = "#161d27", "#273142"
BLUE, GREEN, PURPLE, AMBER, CYAN, RED, ORANGE = (
    "#4ea1ff", "#3ecf8e", "#b48cff", "#ffb547", "#5fd3e6", "#ff5d5d", "#ff9f43")
TG_BLUE, WA_GREEN, AWS_ORANGE = "#2aabee", "#25d366", "#ff9900"


def esc(s: str) -> str:
    return escape(s, {'"': "&quot;"})


def tw(s: str, size: float) -> float:
    """Rough rendered width of a string, enough to size bubbles and chips."""
    w = 0.0
    for ch in s:
        if ord(ch) >= 0x2E80:
            w += 1.0
        elif ch in "il.,:;|!'·":
            w += 0.3
        elif ch == " ":
            w += 0.29
        elif ch.isupper() or ch in "mwMW@%":
            w += 0.7
        else:
            w += 0.55
    return w * size


def T(x, y, s, size=15, fill=TEXT, weight=None, anchor=None, cls=None, opacity=None, ls=None):
    a = [f'x="{x:g}"', f'y="{y:g}"', f'font-size="{size:g}"', f'fill="{fill}"']
    if weight:
        a.append(f'font-weight="{weight}"')
    if anchor:
        a.append(f'text-anchor="{anchor}"')
    if cls:
        a.append(f'class="{cls}"')
    if opacity is not None:
        a.append(f'opacity="{opacity}"')
    if ls:
        a.append(f'letter-spacing="{ls}"')
    return f'<text {" ".join(a)}>{esc(s)}</text>'


def TR(x, y, parts, size=15, anchor=None):
    """One line of text in several colours: parts = [(text, fill, weight), ...]."""
    spans = "".join(
        f'<tspan fill="{f}"{f" font-weight={chr(34)}{w}{chr(34)}" if w else ""}>{esc(s)}</tspan>'
        for s, f, w in parts)
    anc = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x:g}" y="{y:g}" font-size="{size:g}"{anc}>{spans}</text>'


def svg(w, h, lang, title, desc, body, css=""):
    font = FONT_JA if lang == "ja" else FONT_EN
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc">
<title id="title">{esc(title)}</title>
<desc id="desc">{esc(desc)}</desc>
<style>
text {{ font-family: {font}; }}
.mono {{ font-family: {MONO}; }}
{css}
</style>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#151c27"/>
  </linearGradient>
  <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
    <circle cx="1" cy="1" r="1" fill="#ffffff" opacity="0.05"/>
  </pattern>
  <filter id="glow" x="-100%" y="-100%" width="300%" height="300%">
    <feGaussianBlur stdDeviation="3" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <radialGradient id="scan" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="255">
    <stop offset="0" stop-color="{BLUE}" stop-opacity="0.42"/>
    <stop offset="1" stop-color="{BLUE}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="fov" gradientUnits="userSpaceOnUse" x1="0" y1="-140" x2="0" y2="-262">
    <stop offset="0" stop-color="{CYAN}" stop-opacity="0.22"/>
    <stop offset="1" stop-color="{CYAN}" stop-opacity="0"/>
  </linearGradient>
  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0 L10 5 L0 10 z" fill="#4a5870"/>
  </marker>
</defs>
<rect width="{w}" height="{h}" rx="24" fill="url(#bg)"/>
<rect width="{w}" height="{h}" rx="24" fill="url(#dots)"/>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="23.5" fill="none" stroke="#263041"/>
{body}
</svg>
'''


def dot(path_id, color, dur, begin=0.0, r=4.5):
    return (f'<circle r="{r}" fill="{color}" filter="url(#glow)">'
            f'<animateMotion dur="{dur}s" begin="{-begin:g}s" repeatCount="indefinite">'
            f'<mpath xlink:href="#{path_id}" href="#{path_id}"/></animateMotion></circle>')


def pulse(cx, cy, color, r=4):
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}">'
            f'<animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/>'
            f'</circle>')


def icon(kind, cx, cy, c):
    if kind == "robot":
        pts = [(cx + 8 * math.cos(math.radians(a)), cy + 8 * math.sin(math.radians(a)))
               for a in range(30, 390, 60)]
        legs = "".join(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{cx + 14 * math.cos(math.radians(a)):.1f}" '
            f'y2="{cy + 14 * math.sin(math.radians(a)):.1f}" stroke="{c}" stroke-width="2" '
            f'stroke-linecap="round"/>'
            for (x, y), a in zip(pts, range(30, 390, 60)))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return legs + f'<polygon points="{poly}" fill="none" stroke="{c}" stroke-width="2"/>'
    if kind == "server":
        return "".join(
            f'<rect x="{cx - 10}" y="{cy - 10 + i * 7}" width="20" height="5" rx="1.5" fill="none" '
            f'stroke="{c}" stroke-width="1.8"/><circle cx="{cx + 6}" cy="{cy - 7.5 + i * 7}" r="1" '
            f'fill="{c}"/>' for i in range(3))
    if kind == "cloud":
        return (f'<path d="M{cx - 10} {cy + 6} a5 5 0 0 1 1-10 a7 7 0 0 1 13-2 a5 5 0 0 1 6 6 '
                f'a4 4 0 0 1-1 6 z" fill="none" stroke="{c}" stroke-width="2" '
                f'stroke-linejoin="round"/>')
    if kind == "spark":
        return (f'<path d="M{cx} {cy - 12} Q{cx + 2} {cy - 2} {cx + 12} {cy} Q{cx + 2} {cy + 2} {cx} {cy + 12} '
                f'Q{cx - 2} {cy + 2} {cx - 12} {cy} Q{cx - 2} {cy - 2} {cx} {cy - 12} z" fill="none" '
                f'stroke="{c}" stroke-width="2" stroke-linejoin="round"/>'
                f'<circle cx="{cx + 9}" cy="{cy - 9}" r="1.8" fill="{c}"/>')
    if kind == "phone":
        return (f'<rect x="{cx - 7}" y="{cy - 11}" width="14" height="22" rx="3" fill="none" '
                f'stroke="{c}" stroke-width="2"/><line x1="{cx - 2}" y1="{cy + 7}" x2="{cx + 2}" '
                f'y2="{cy + 7}" stroke="{c}" stroke-width="2" stroke-linecap="round"/>')
    if kind == "laptop":
        return (f'<rect x="{cx - 10}" y="{cy - 9}" width="20" height="13" rx="2" fill="none" '
                f'stroke="{c}" stroke-width="2"/><line x1="{cx - 14}" y1="{cy + 8}" x2="{cx + 14}" '
                f'y2="{cy + 8}" stroke="{c}" stroke-width="2" stroke-linecap="round"/>')
    raise ValueError(kind)


def card(x, y, w, h, accent, kind, title, sub, bullets, why=None, why_label="Why"):
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{CARD}" stroke="{CARD_LINE}"/>',
         f'<path d="M{x + 18} {y + 1.5} H{x + w - 18}" stroke="{accent}" stroke-width="3" '
         f'stroke-linecap="round"/>',
         f'<circle cx="{x + 36}" cy="{y + 42}" r="21" fill="{accent}" fill-opacity="0.13" '
         f'stroke="{accent}" stroke-opacity="0.5"/>',
         icon(kind, x + 36, y + 42, accent),
         T(x + 68, y + 38, title, 19, TEXT, 700),
         T(x + 68, y + 60, sub, 13.5, MUTED),
         pulse(x + w - 22, y + 24, accent),
         f'<line x1="{x + 16}" y1="{y + 80}" x2="{x + w - 16}" y2="{y + 80}" stroke="{CARD_LINE}"/>']
    by = y + 110
    for b in bullets:
        o.append(f'<circle cx="{x + 27}" cy="{by - 5}" r="3" fill="{accent}"/>')
        o.append(T(x + 40, by, b, 15))
        by += 30
    if why:
        o.append(f'<rect x="{x + 14}" y="{y + h - 52}" width="{w - 28}" height="38" rx="10" '
                 f'fill="{accent}" fill-opacity="0.1" stroke="{accent}" stroke-opacity="0.25"/>')
        o.append(TR(x + 28, y + h - 27, [(why_label + "  ", accent, 700), (why, "#cfd7e2", None)], 14))
    return "\n".join(o)


# ----------------------------------------------------------------------------- the robot drawing
LEGS = [  # name, mount x, mount y, direction (deg, SVG), tripod group, side
    ("LF", -42, -112, 220, "A", "L"),
    ("LM", -92, 0, 180, "B", "L"),
    ("LR", -42, 112, 140, "A", "L"),
    ("RF", 42, -112, -40, "B", "R"),
    ("RM", 92, 0, 0, "A", "R"),
    ("RR", 42, 112, 40, "B", "R"),
]
LEG_COLOR = {"LF": "#8fd0ff", "LM": BLUE, "LR": "#2a6fd0",
             "RF": "#ffd08a", "RM": ORANGE, "RR": "#d9701c"}  # same colours as the 3D simulator
COXA, FEMUR, TIBIA = 26, 62, 78
BODY = [(-45, -125), (45, -125), (95, 0), (45, 125), (-45, 125), (-95, 0)]


def hexapod(period=1.2, amp=9.0):
    """Top view of the robot, front up, centred on (0, 0): tripod gait and a spinning LiDAR."""
    o = []
    r, a = 255, math.radians(17)
    o.append(
        '<g transform="translate(0 -35)">'
        '<g><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="3s" '
        'repeatCount="indefinite"/>'
        f'<path d="M0 0 L{r * math.cos(-a):.1f} {r * math.sin(-a):.1f} A{r} {r} 0 0 1 '
        f'{r * math.cos(a):.1f} {r * math.sin(a):.1f} Z" fill="url(#scan)"/></g>'
        + "".join(
            f'<circle r="30" fill="none" stroke="{BLUE}" stroke-width="1.5">'
            f'<animate attributeName="r" values="30;250" dur="3s" begin="-{b}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".45;0" dur="3s" begin="-{b}s" '
            f'repeatCount="indefinite"/></circle>' for b in (0, 1.5))
        + "</g>")
    o.append('<polygon points="0,-140 -78,-262 78,-262" fill="url(#fov)"/>')
    knee = COXA + FEMUR
    for name, mx, my, base, grp, side in LEGS:
        c = LEG_COLOR[name]
        s = 1 if side == "L" else -1
        # A slight knee bend: front legs reach forward, rear legs back, as a spider stands.
        bend = math.radians(16 * {"F": 1.0, "M": 0.35, "R": -0.7}[name[1]] * s)
        fx, fy = knee + TIBIA * math.cos(bend), TIBIA * math.sin(bend)
        begin = "0s" if grp == "A" else f"-{period / 2:g}s"
        o.append(
            f'<g transform="translate({mx} {my})"><g>'
            f'<animateTransform attributeName="transform" type="rotate" values="{-amp * s:g};{amp * s:g};{-amp * s:g}" '
            f'keyTimes="0;0.5;1" calcMode="spline" keySplines=".45 0 .55 1;.45 0 .55 1" '
            f'dur="{period:g}s" begin="{begin}" repeatCount="indefinite"/>'
            f'<g transform="rotate({base})">'
            f'<line x1="0" y1="0" x2="{COXA}" y2="0" stroke="{c}" stroke-width="13" stroke-linecap="round"/>'
            f'<line x1="{COXA}" y1="0" x2="{knee}" y2="0" stroke="{c}" stroke-width="11" stroke-linecap="round"/>'
            f'<line x1="{knee}" y1="0" x2="{fx:.1f}" y2="{fy:.1f}" stroke="{c}" stroke-width="8" stroke-linecap="round"/>'
            + "".join(f'<circle cx="{jx}" cy="0" r="6" fill="#dfe5ee" stroke="#0d1117" stroke-width="1.5"/>'
                      for jx in (0, COXA, knee))
            + f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="6.5" fill="{c}" stroke="#0d1117" stroke-width="2">'
              f'<animate attributeName="r" values="6.5;10.5;6.5;6.5" keyTimes="0;0.25;0.5;1" dur="{period:g}s" '
              f'begin="{begin}" repeatCount="indefinite"/></circle>'
              '</g></g></g>')
    pts = " ".join(f"{x},{y}" for x, y in BODY)
    o.append(f'<polygon points="{pts}" fill="#1c2430" stroke="#3c495c" stroke-width="2" stroke-linejoin="round"/>')
    inner = " ".join(f"{x * 0.86:.1f},{y * 0.9:.1f}" for x, y in BODY)
    o.append(f'<polygon points="{inner}" fill="none" stroke="#2a3443" stroke-width="1"/>')
    # camera
    o.append(f'<rect x="-20" y="-146" width="40" height="20" rx="6" fill="#232c3a" stroke="{CYAN}" stroke-width="1.5"/>')
    o.append(f'<circle cx="0" cy="-136" r="6" fill="#0d1117" stroke="{CYAN}" stroke-width="2"/>')
    # microphone and speaker
    o.append(f'<rect x="-33" y="-104" width="10" height="18" rx="5" fill="#232c3a" stroke="{AMBER}" stroke-width="1.5"/>')
    o.append(f'<circle cx="28" cy="-95" r="9" fill="#232c3a" stroke="{AMBER}" stroke-width="1.5"/>')
    o.append(f'<circle cx="28" cy="-95" r="3.5" fill="{AMBER}"/>')
    for i, d in enumerate(("M41 -102 Q46 -95 41 -88", "M47 -107 Q55 -95 47 -83")):
        o.append(f'<path d="{d}" fill="none" stroke="{AMBER}" stroke-width="1.6" stroke-linecap="round">'
                 f'<animate attributeName="opacity" values="0;1;0" dur="1.6s" begin="-{i * 0.3:g}s" '
                 f'repeatCount="indefinite"/></path>')
    # LiDAR puck
    o.append(f'<circle cx="0" cy="-35" r="30" fill="#1a2230" stroke="{BLUE}" stroke-width="2"/>')
    o.append('<circle cx="0" cy="-35" r="18" fill="#10151d" stroke="#2b5ea8"/>')
    o.append(f'<circle cx="0" cy="-35" r="5" fill="{BLUE}" filter="url(#glow)"/>')
    # Raspberry Pi
    o.append(f'<rect x="-42" y="4" width="84" height="44" rx="5" fill="#11402b" stroke="{GREEN}" stroke-width="1.5"/>')
    o.append('<rect x="-11" y="10" width="22" height="16" rx="2" fill="#1d5c3f"/>')
    o.append('<rect x="30" y="9" width="9" height="11" rx="1" fill="#2c7a55"/>'
             '<rect x="30" y="24" width="9" height="11" rx="1" fill="#2c7a55"/>')
    o.append(T(0, 41, "Pi 4", 11, "#d8ffe9", 700, "middle"))
    # SSC-32U
    o.append(f'<rect x="-38" y="58" width="76" height="22" rx="4" fill="#122646" stroke="{BLUE}" stroke-width="1.5"/>')
    o.append(T(0, 73, "SSC-32U", 10.5, "#cfe3ff", 700, "middle", "mono"))
    # E-stop
    o.append(f'<circle cx="0" cy="104" r="10" fill="{RED}" stroke="#ffc2c2" stroke-width="2"/>')
    o.append('<circle cx="0" cy="104" r="4.5" fill="#ff9a9a"/>')
    return "\n".join(o)


# ----------------------------------------------------------------------------- 1. banner
BANNER = {
    "en": {
        "label": "SPIDER ROBOT · RASPBERRY PI 4",
        "sub": "A six-legged robot that walks, talks and sees",
        "chips": ["Arabic voice", "LiDAR safety", "Works offline", "Telegram + WhatsApp"],
        "title": "Lowi, a smart spider robot",
        "desc": "Banner: an animated top view of the six-legged robot walking with its LiDAR spinning.",
    },
    "ja": {
        "label": "スパイダーロボット · RASPBERRY PI 4",
        "sub": "歩いて、話して、見る。6本脚のロボット",
        "chips": ["アラビア語で会話", "LiDARで安全", "オフラインで動作", "Telegram + WhatsApp"],
        "title": "Lowi スマート・スパイダーロボット",
        "desc": "バナー：LiDARを回しながら歩く6本脚ロボットのアニメーション。",
    },
}


def banner(lang):
    s = BANNER[lang]
    w, h = 1200, 380
    o = [f'<defs><linearGradient id="tg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffffff"/>'
         f'<stop offset="1" stop-color="#9fc9ff"/></linearGradient>'
         f'<radialGradient id="halo"><stop offset="0" stop-color="{BLUE}" stop-opacity="0.18"/>'
         f'<stop offset="1" stop-color="{BLUE}" stop-opacity="0"/></radialGradient></defs>',
         T(64, 108, s["label"], 14, AMBER, 700, ls="3"),
         f'<text x="60" y="196" font-size="88" font-weight="800" fill="url(#tg)" letter-spacing="-1">Lowi</text>',
         T(64, 240, s["sub"], 24, "#c5cdd8")]
    x = 64
    for chip in s["chips"]:
        cw = tw(chip, 15) + 34
        o.append(f'<rect x="{x:.0f}" y="270" width="{cw:.0f}" height="36" rx="18" fill="#18202b" stroke="#2f3a4c"/>')
        o.append(T(x + cw / 2, 293, chip, 15, "#dbe3ee", 600, "middle"))
        x += cw + 10
    o.append('<circle cx="910" cy="190" r="190" fill="url(#halo)"/>')
    o.append(f'<g transform="translate(910 196) scale(0.6)">{hexapod()}</g>')
    return svg(w, h, lang, s["title"], s["desc"], "\n".join(o))


# ----------------------------------------------------------------------------- 2. architecture
ARCH = {
    "en": {
        "title": "How everything connects",
        "sub": "Each part has one job, and one rule holds them together: if the network dies, the robot is still safe.",
        "why": "Why",
        "robot": ("Robot", "Raspberry Pi 4 · 4 GB",
                  ["Walks: IK + gait at 50 Hz", "Stops itself: LiDAR + IMU",
                   "Hears & talks: Whisper, Piper", "Gateway: one source of motion"],
                  "Safety never waits for Wi-Fi"),
        "server": ("Home server", "i7-8700 · 15 GB · CPU only",
                   ["Brain: planner + dashboard", "Lowi: chat, Telegram, WhatsApp",
                    "Vision: LFM2.5-VL-1.6B", "Hard questions: LFM2.5-1.2B"],
                   "Heavy work that can wait 1 s"),
        "cloud": ("AI cloud", "Escalation only",
                  ["NVIDIA NIM · Claude · Gemini", "Deep reasoning, hard images"],
                  "Optional: only when online"),
        "aws": ("AWS", "EC2 on demand",
                ["3D mapping (SLAM) on demand", "Lowi moved home on 2026-11-17", "Planned, not built yet"],
                "Stops itself, never required"),
        "l_aws": "Tailscale",
        "phone": ("Your phone", "Remote control",
                  ["Telegram: tasks, photos, stop", "WhatsApp: chat with Lowi",
                   "Dashboard over Tailscale", "Lowi app: iPhone and iPad"],
                  "Always through the brain"),
        "laptop": ("Your laptop", "Development",
                   ["Simulator and tests", "Deploy + SSH via Tailscale"]),
        "l_mqtt": ("MQTT + mTLS", "via Tailscale"),
        "l_https": ("HTTPS", "when online"),
        "l_chat": ("Telegram", "WhatsApp"),
        "l_ssh1": "SSH · deploy",
        "l_ssh2": "SSH",
        "legend": ["Robot → server: hard questions, photos", "Server → robot: answers, plans",
                   "Dashed: optional or maintenance"],
        "rule": ("Rule", "If the network dies, safety, walking and simple voice commands keep working on the robot."),
        "desc": ("Diagram of the robot (Raspberry Pi 4), the home server, AWS, the AI cloud, the owner's "
                 "phone and laptop, with animated messages moving between them."),
    },
    "ja": {
        "title": "全体のつながり",
        "sub": "それぞれに役割があり、ルールはひとつ：ネットが切れても、ロボットは安全。",
        "why": "理由",
        "robot": ("ロボット", "Raspberry Pi 4 · 4 GB",
                  ["歩行：IK＋歩容 50 Hz", "自動停止：LiDAR＋IMU",
                   "音声：Whisper＋Piper", "ゲートウェイ：動作指令を一本化"],
                  "安全はWi-Fiを待たない"),
        "server": ("ホームサーバー", "i7-8700 · 15 GB · CPUのみ",
                   ["ブレイン：計画＋ダッシュボード", "Lowi：会話・Telegram・WhatsApp",
                    "視覚：LFM2.5-VL-1.6B", "難しい質問：LFM2.5-1.2B"],
                   "1秒待てる重い処理"),
        "cloud": ("AIクラウド", "エスカレーション専用",
                  ["NVIDIA NIM・Claude・Gemini", "高度な推論・難しい画像"],
                  "任意：オンライン時のみ"),
        "aws": ("AWS", "必要時のEC2",
                ["必要時のみ3Dマッピング（SLAM）", "Lowiは2026-11-17に自宅へ移行", "予定、まだ未構築"],
                "自動で停止。必須ではない"),
        "l_aws": "Tailscale",
        "phone": ("スマートフォン", "遠隔操作",
                  ["Telegram：タスク・写真・停止", "WhatsApp：Lowiと会話",
                   "ダッシュボード（Tailscale）", "Lowiアプリ：iPhone・iPad"],
                  "必ずブレインを経由"),
        "laptop": ("ノートPC", "開発",
                   ["シミュレーターとテスト", "Tailscale経由でデプロイ・SSH"]),
        "l_mqtt": ("MQTT + mTLS", "Tailscale経由"),
        "l_https": ("HTTPS", "オンライン時"),
        "l_chat": ("Telegram", "WhatsApp"),
        "l_ssh1": "SSH · デプロイ",
        "l_ssh2": "SSH",
        "legend": ["ロボット → サーバー：難しい質問・写真", "サーバー → ロボット：回答・計画",
                   "破線：任意の接続・メンテナンス"],
        "rule": ("ルール", "ネットが切れても、安全・歩行・簡単な音声コマンドはロボット単体で動き続ける。"),
        "desc": ("ロボット（Raspberry Pi 4）、ホームサーバー、AWS、AIクラウド、スマートフォン、ノートPCの接続図。"
                 "メッセージの流れをアニメーションで表示。"),
    },
}


def architecture(lang):
    s = ARCH[lang]
    w, h = 1200, 884
    why = s["why"]
    paths = {
        "p_rs": "M340 268 H450", "p_sr": "M450 300 H340",
        "p_sc": "M750 212 H860", "p_cs": "M860 230 H750",
        "p_sp": "M750 420 C805 420 805 560 860 560", "p_ps": "M860 560 C805 560 805 420 750 420",
        "p_sa": "M588 470 V520", "p_as": "M612 520 V470",
        "p_lr": "M190 540 V470", "p_ls": "M340 600 H380 Q395 600 395 585 V455 Q395 440 410 440 H450",
    }
    o = [T(48, 66, s["title"], 30, TEXT, 700), T(48, 98, s["sub"], 16.5, MUTED)]
    o.append("<defs>" + "".join(f'<path id="{k}" d="{v}"/>' for k, v in paths.items()) + "</defs>")
    solid = 'fill="none" stroke="#33405a" stroke-width="2"'
    dashed = 'fill="none" stroke-width="2" stroke-dasharray="6 6"'
    march = ('<animate attributeName="stroke-dashoffset" from="0" to="-24" dur="1.2s" '
             'repeatCount="indefinite"/>')
    o += [f'<path d="{paths["p_rs"]}" {solid}/>', f'<path d="{paths["p_sr"]}" {solid}/>',
          f'<path d="{paths["p_sc"]}" stroke="{PURPLE}" stroke-opacity=".55" {dashed}>{march}</path>',
          f'<path d="{paths["p_cs"]}" stroke="{PURPLE}" stroke-opacity=".55" {dashed}>{march}</path>',
          f'<path d="{paths["p_sp"]}" {solid}/>',
          f'<path d="{paths["p_sa"]}" stroke="{AWS_ORANGE}" stroke-opacity=".55" {dashed}>{march}</path>',
          f'<path d="{paths["p_as"]}" stroke="{AWS_ORANGE}" stroke-opacity=".55" {dashed}>{march}</path>',
          f'<path d="{paths["p_lr"]}" stroke="{CYAN}" stroke-opacity=".5" {dashed}>{march}</path>',
          f'<path d="{paths["p_ls"]}" stroke="{CYAN}" stroke-opacity=".5" {dashed}>{march}</path>']
    o += [dot("p_rs", BLUE, 2.0, 0), dot("p_rs", BLUE, 2.0, 1.0),
          dot("p_sr", GREEN, 2.0, 0.5), dot("p_sr", GREEN, 2.0, 1.5),
          f'<g><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.2;.8;1" dur="5s" repeatCount="indefinite"/>'
          + dot("p_sc", PURPLE, 2.5, 0) + dot("p_cs", PURPLE, 2.5, 1.25) + "</g>",
          f'<g><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.2;.8;1" dur="4s" begin="-2s" repeatCount="indefinite"/>'
          + dot("p_sa", GREEN, 1.4, 0, 4) + dot("p_as", AWS_ORANGE, 1.4, 0.7, 4) + "</g>",
          dot("p_ps", AMBER, 2.6, 0), dot("p_ps", AMBER, 2.6, 1.3),
          dot("p_sp", GREEN, 2.6, 0.65), dot("p_sp", GREEN, 2.6, 1.95),
          dot("p_lr", CYAN, 2.4, 0, 3.5), dot("p_ls", CYAN, 3.4, 0, 3.5)]
    # link labels
    o.append(T(395, 232, s["l_mqtt"][0], 13, TEXT, 700, "middle"))
    o.append(T(395, 249, s["l_mqtt"][1], 12.5, MUTED, None, "middle"))
    o.append(T(805, 180, s["l_https"][0], 13, TEXT, 700, "middle"))
    o.append(T(805, 197, s["l_https"][1], 12.5, MUTED, None, "middle"))
    o.append(f'<rect x="763" y="469" width="84" height="42" rx="9" fill="#121820" stroke="#2a3445"/>')
    o.append(T(805, 486, s["l_chat"][0], 12.5, TG_BLUE, 700, "middle"))
    o.append(T(805, 503, s["l_chat"][1], 12.5, WA_GREEN, 700, "middle"))
    o.append(T(202, 510, s["l_ssh1"], 12.5, MUTED))
    o.append(T(386, 528, s["l_ssh2"], 12.5, MUTED, None, "end"))
    o.append(T(624, 500, s["l_aws"], 12.5, MUTED))
    # cards
    r, sv, c, p, lp, a = s["robot"], s["server"], s["cloud"], s["phone"], s["laptop"], s["aws"]
    o.append(card(40, 140, 300, 330, BLUE, "robot", r[0], r[1], r[2], r[3], why))
    o.append(card(450, 140, 300, 330, GREEN, "server", sv[0], sv[1], sv[2], sv[3], why))
    o.append(card(860, 140, 300, 220, PURPLE, "spark", c[0], c[1], c[2], c[3], why))
    o.append(card(860, 410, 300, 300, AMBER, "phone", p[0], p[1], p[2], p[3], why))
    o.append(card(40, 540, 300, 170, CYAN, "laptop", lp[0], lp[1], lp[2]))
    o.append(card(450, 520, 300, 250, AWS_ORANGE, "cloud", a[0], a[1], a[2], a[3], why))
    # legend
    lx, ly = 48, 748
    o.append(f'<circle cx="{lx + 6}" cy="{ly - 5}" r="4.5" fill="{BLUE}"/>' + T(lx + 20, ly, s["legend"][0], 13.5, MUTED))
    o.append(f'<circle cx="{lx + 6}" cy="{ly + 21}" r="4.5" fill="{GREEN}"/>' + T(lx + 20, ly + 26, s["legend"][1], 13.5, MUTED))
    o.append(f'<line x1="{lx}" y1="{ly + 47}" x2="{lx + 13}" y2="{ly + 47}" stroke="{MUTED}" stroke-width="2" '
             f'stroke-dasharray="4 3"/>' + T(lx + 20, ly + 52, s["legend"][2], 13.5, MUTED))
    # rule
    o.append(f'<rect x="40" y="818" width="1120" height="44" rx="12" fill="#18202b" stroke="#2a3445"/>')
    o.append(TR(64, 846, [(s["rule"][0] + "   ", AMBER, 700), (s["rule"][1], "#d5dce6", None)], 15))
    return svg(w, h, lang, s["title"], s["desc"], "\n".join(o))


# ----------------------------------------------------------------------------- 3. inside the robot
ROBOT = {
    "en": {
        "title": "Inside the robot",
        "sub": "Every part, and what it is for",
        "front": "FRONT",
        "callouts": [
            ("Camera", "Photos on request, analysed by the server", CYAN),
            ("Microphone + speaker", "Wake word “Lowi”, listens and speaks Arabic", AMBER),
            ("Unitree L2 4D LiDAR + IMU", "360° obstacle view, tilt and fall detection", BLUE),
            ("Raspberry Pi 4 · 4 GB", "Core 0: 50 Hz body loop · cores 1–3: voice and AI", GREEN),
            ("Lynxmotion SSC-32U", "USB servo board: turns joint angles into pulses", BLUE),
            ("E-stop", "Stays latched through reboots; voice can never release it", RED),
            ("18 servos · 6 legs × 3 joints", "Tripod, ripple and wave gaits", ORANGE),
        ],
        "does": "WHAT IT DOES",
        "chips": ["Walks · 3 gaits", "Stops on its own", "Talks in Arabic", "Sees on request",
                  "17 expressive moves", "Works offline"],
        "desc": "Top view of the hexapod with callouts for the camera, audio, LiDAR, Raspberry Pi, servo board, E-stop and servos.",
    },
    "ja": {
        "title": "ロボットの中身",
        "sub": "各パーツとその役割",
        "front": "前",
        "callouts": [
            ("カメラ", "必要な時だけ撮影し、サーバーで解析", CYAN),
            ("マイク＋スピーカー", "ウェイクワード「Lowi」、アラビア語で会話", AMBER),
            ("Unitree L2 4D LiDAR＋IMU", "360°の障害物検知、傾き・転倒の検知", BLUE),
            ("Raspberry Pi 4 · 4 GB", "コア0：50 Hzの制御ループ、コア1–3：音声とAI", GREEN),
            ("Lynxmotion SSC-32U", "USBサーボボード：関節角度をパルスに変換", BLUE),
            ("非常停止", "再起動後も保持。音声では解除できない", RED),
            ("サーボ18個・脚6本×関節3", "トライポッド・リップル・ウェーブ歩容", ORANGE),
        ],
        "does": "できること",
        "chips": ["3種類の歩容で歩く", "自分で止まる", "アラビア語で話す", "頼めば見る",
                  "17種類のジェスチャー", "オフラインで動く"],
        "desc": "6本脚ロボットの上面図。カメラ、音声、LiDAR、Raspberry Pi、サーボボード、非常停止、サーボの説明付き。",
    },
}


def robot(lang):
    s = ROBOT[lang]
    w, h = 1200, 750
    cx, cy = 410, 422
    o = [T(48, 66, s["title"], 30, TEXT, 700), T(48, 98, s["sub"], 16.5, MUTED),
         T(cx, 150, s["front"], 11.5, DIM, 700, "middle", ls="2"),
         f'<g transform="translate({cx} {cy})">{hexapod()}</g>']
    # component anchor points (absolute), in the same order as the callouts
    anchors = [(cx + 20, cy - 136), (cx + 37, cy - 95), (cx + 30, cy - 35), (cx + 42, cy + 26),
               (cx + 38, cy + 69), (cx + 10, cy + 104), (cx + 62, cy + 129)]
    rows = [170, 243, 316, 389, 462, 535, 608]
    for i, ((px, py), ry, (title, desc, col)) in enumerate(zip(anchors, rows, s["callouts"])):
        o.append(f'<path d="M{px} {py} L700 {ry} H726" fill="none" stroke="#5b6676" stroke-width="1.3" '
                 f'stroke-dasharray="3 4"/>')
        o.append(f'<circle cx="{px}" cy="{py}" r="3.5" fill="{col}"/>')
        o.append(f'<circle cx="744" cy="{ry - 5}" r="13" fill="{col}" fill-opacity=".15" stroke="{col}" stroke-opacity=".7"/>')
        o.append(T(744, ry, str(i + 1), 13, col, 700, "middle"))
        o.append(T(768, ry, title, 17, TEXT, 700))
        o.append(T(768, ry + 22, desc, 14.5, MUTED))
    o.append(T(48, 668, s["does"], 12.5, DIM, 700, ls="2"))
    cw = (1104 - 5 * 12) / 6
    for i, chip in enumerate(s["chips"]):
        x = 48 + i * (cw + 12)
        o.append(f'<rect x="{x:.1f}" y="682" width="{cw:.1f}" height="40" rx="20" fill="#18202b" '
                 f'stroke="{BLUE}" stroke-opacity=".2">'
                 f'<animate attributeName="stroke-opacity" values=".2;1;.2;.2" keyTimes="0;.08;.22;1" '
                 f'dur="3.6s" begin="{i * 0.6:g}s" repeatCount="indefinite"/></rect>')
        o.append(T(x + cw / 2, 707, chip, 14.5, "#dbe3ee", 600, "middle"))
    return svg(w, h, lang, s["title"], s["desc"], "\n".join(o))


# ----------------------------------------------------------------------------- 4. Telegram and WhatsApp
MSG = {
    "en": {
        "title": "Telegram and WhatsApp",
        "sub": "Two apps, two jobs. Both reach the robot only through the brain.",
        "tg_name": ("Lowi", "bot"), "wa_name": ("Lowi", "online"),
        "tg": [("me", ["/photo", "what's on the table?"]), ("photo", ["A cup and a laptop."]),
               ("ask", ["Walk 1 m forward?"]), ("me", ["/stop"]), ("bot", ["Stopped. Standing still."])],
        "tg_buttons": ("Approve", "Reject"),
        "wa": [("me", ["Hi Lowi, is the", "robot OK?"]), ("bot", ["All good: standing,", "nothing in front."]),
               ("voice", ["0:04"]), ("bot", ["Got it, saved to", "memory."]),
               ("alert", ["Alert: robot stopped,", "obstacle ahead."])],
        "server": ("Home server", "Lowi + brain", ["Keeps every word from every channel", "Photos only when you ask"]),
        "robot": ("Robot", "through the gateway", "All safety rules still apply"),
        "rules": ("Same rules for every channel",
                  ["Stop always wins", "Risky moves wait for your approval",
                   "Text the camera sees never moves the robot"]),
        "tg_role": ("Telegram · control",
                    ["Tasks in plain words or voice", "/status  /photo  /stop  /estop",
                     "Approve or reject risky moves", "Alerts: obstacle, fall, link lost",
                     "Answers owner accounts only"]),
        "wa_role": ("WhatsApp · conversation",
                    ["Chat with Lowi, 1:1 or in groups", "Voice notes are transcribed",
                     "Short alerts, rate-limited", "Every word goes to Lowi's memory"]),
        "desc": "Two animated phone chats, Telegram for control and WhatsApp for conversation, both connected to the home server and then the robot.",
    },
    "ja": {
        "title": "Telegram と WhatsApp",
        "sub": "2つのアプリ、2つの役割。どちらもブレインを通してロボットに届く。",
        "tg_name": ("Lowi", "bot"), "wa_name": ("Lowi", "オンライン"),
        "tg": [("me", ["/photo", "机の上に何がある？"]), ("photo", ["カップとノートPC。"]),
               ("ask", ["1 m 前進しますか？"]), ("me", ["/stop"]), ("bot", ["停止しました。"])],
        "tg_buttons": ("承認", "拒否"),
        "wa": [("me", ["Lowi、ロボットは", "大丈夫？"]), ("bot", ["大丈夫。立っていて、", "前に障害物なし。"]),
               ("voice", ["0:04"]), ("bot", ["了解、記憶に保存したよ。"]),
               ("alert", ["通知：前方に障害物、", "ロボットが停止。"])],
        "server": ("ホームサーバー", "Lowi＋ブレイン", ["全チャネルの会話をすべて記憶", "写真は頼まれた時だけ"]),
        "robot": ("ロボット", "ゲートウェイ経由", "安全ルールは常に有効"),
        "rules": ("全チャネル共通のルール",
                  ["停止が常に最優先", "危険な動作はあなたの承認待ち", "カメラに映った文字ではロボットは動かない"]),
        "tg_role": ("Telegram：操作",
                    ["言葉や音声でタスクを依頼", "/status  /photo  /stop  /estop",
                     "危険な動作を承認・拒否", "通知：障害物・転倒・接続断", "オーナーのアカウントだけに応答"]),
        "wa_role": ("WhatsApp：会話",
                    ["Lowiと1対1やグループで会話", "ボイスメモを文字起こし",
                     "短い通知（送信回数を制限）", "すべての会話をLowiが記憶"]),
        "desc": "Telegram（操作）とWhatsApp（会話）の2つのチャット画面のアニメーション。どちらもホームサーバーを経由してロボットにつながる。",
    },
}
CYCLE = 10.0


def bubbles(prefix, items, x0, x1, y, me_col, bot_col, buttons=None, offset=0.0):
    """Chat bubbles from the top of a phone screen; each one fades in on a 10 s loop (SMIL)."""
    o = []
    for i, (kind, lines) in enumerate(items):
        p = (0.5 + i * 1.3 + offset) / CYCLE
        keys = f"0;{p:.3f};{p + 0.03:.3f};0.92;0.97;1"
        anim = (f'<animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="{keys}" dur="{CYCLE:g}s" '
                f'repeatCount="indefinite"/>'
                f'<animateTransform attributeName="transform" type="translate" '
                f'values="0 10;0 10;0 0;0 0;0 0;0 0" keyTimes="{keys}" dur="{CYCLE:g}s" repeatCount="indefinite"/>')
        g = []
        if kind == "voice":
            bw, bh = 168, 40
            bx = x1 - bw
            g.append(f'<rect x="{bx}" y="{y}" width="{bw}" height="{bh}" rx="12" fill="{me_col}"/>')
            g.append(f'<path d="M{bx + 14} {y + 12} L{bx + 28} {y + 20} L{bx + 14} {y + 28} z" fill="#dff5ee"/>')
            heights = [6, 12, 18, 10, 16, 22, 14, 8, 18, 12, 20, 9, 14, 7, 11]
            for k, hh in enumerate(heights):
                g.append(f'<rect x="{bx + 38 + k * 6}" y="{y + 20 - hh / 2}" width="3" height="{hh}" rx="1.5" fill="#bfe8dc"/>')
            g.append(T(bx + bw - 10, y + 25, lines[0], 12, "#cfe9e1", None, "end"))
            y += bh + 9
        else:
            size, lh = 13.5, 18
            textw = max(tw(line, size) for line in lines)
            photo = kind == "photo"
            bw = 176 if photo else min(max(textw + 26, 60), 186)
            bh = (90 if photo else 0) + 16 + lh * len(lines)
            is_me = kind == "me"
            bx = x1 - bw if is_me else x0
            fill = me_col if is_me else bot_col
            g.append(f'<rect x="{bx:.1f}" y="{y}" width="{bw:.1f}" height="{bh}" rx="12" fill="{fill}"/>')
            ty = y + 23
            if photo:
                g.append(f'<rect x="{bx + 6}" y="{y + 6}" width="{bw - 12}" height="80" rx="8" fill="#2a3f55"/>')
                g.append(f'<line x1="{bx + 14}" y1="{y + 70}" x2="{bx + bw - 14}" y2="{y + 70}" stroke="#6d87a3" stroke-width="3"/>')
                g.append(f'<rect x="{bx + 36}" y="{y + 46}" width="18" height="24" rx="3" fill="#d9e4f0"/>'
                         f'<path d="M{bx + 54} {y + 52} q8 0 8 7 q0 7 -8 7" fill="none" stroke="#d9e4f0" stroke-width="3"/>')
                g.append(f'<rect x="{bx + 92}" y="{y + 30}" width="54" height="34" rx="3" fill="#9fb7cf"/>'
                         f'<rect x="{bx + 86}" y="{y + 64}" width="66" height="5" rx="2" fill="#c8d6e4"/>')
                ty = y + 90 + 23
            if kind == "alert":
                g.append(f'<rect x="{bx}" y="{y}" width="4" height="{bh}" rx="2" fill="{AMBER}"/>')
            col = "#ffd9a0" if kind == "alert" else "#eef3f8"
            for line in lines:
                g.append(T(bx + 13, ty, line, size, col))
                ty += lh
            y += bh + 9
            if kind == "ask" and buttons:
                half = (bw - 6) / 2
                for k, label in enumerate(buttons):
                    btx = bx + k * (half + 6)
                    # The Approve button lights up as if tapped, just before /stop arrives.
                    tap = ('<animate attributeName="fill" values="#22303f;#22303f;#2f6fb0;#2f6fb0;#22303f;#22303f" '
                           f'keyTimes="0;{p + 0.06:.3f};{p + 0.08:.3f};{p + 0.13:.3f};{p + 0.15:.3f};1" '
                           f'dur="{CYCLE:g}s" repeatCount="indefinite"/>') if k == 0 else ""
                    g.append(f'<rect x="{btx:.1f}" y="{y - 4}" width="{half:.1f}" height="28" rx="8" '
                             f'fill="#22303f">{tap}</rect>')
                    g.append(T(btx + half / 2, y + 15, label, 13, "#7cb8ff", 700, "middle"))
                y += 32
        o.append("<g>" + anim + "".join(g) + "</g>")
    return "\n".join(o)


def phone(x, y, w, h, clip_id, screen_bg, header_bg, avatar_col, name, status):
    sx, sy, sw, sh = x + 9, y + 9, w - 18, h - 18
    return "\n".join([
        f'<clipPath id="{clip_id}"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="28"/></clipPath>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="36" fill="#0a0d12" stroke="#2a3240" stroke-width="2"/>',
        f'<g clip-path="url(#{clip_id})">',
        f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="{screen_bg}"/>',
        f'<rect x="{sx}" y="{sy}" width="{sw}" height="54" fill="{header_bg}"/>',
        '</g>',
        f'<circle cx="{sx + 28}" cy="{sy + 28}" r="15" fill="{avatar_col}"/>',
        T(sx + 28, sy + 33, "L", 14, "#ffffff", 700, "middle"),
        T(sx + 52, sy + 25, name, 14.5, "#ffffff", 700),
        T(sx + 52, sy + 42, status, 12, "#9fb0c2"),
    ])


def messaging(lang):
    s = MSG[lang]
    w, h = 1200, 770
    o = [T(48, 66, s["title"], 30, TEXT, 700), T(48, 98, s["sub"], 16.5, MUTED)]
    paths = {"p_tg": "M315 330 C375 330 375 255 430 255", "p_gt": "M430 255 C375 255 375 330 315 330",
             "p_wa": "M885 330 C825 330 825 255 770 255", "p_aw": "M770 255 C825 255 825 330 885 330",
             "p_down": "M600 340 V425"}
    o.append("<defs>" + "".join(f'<path id="{k}" d="{v}"/>' for k, v in paths.items()) + "</defs>")
    for k in ("p_tg", "p_wa", "p_down"):
        o.append(f'<path d="{paths[k]}" fill="none" stroke="#33405a" stroke-width="2"/>')
    o += [dot("p_tg", TG_BLUE, 2.2, 0), dot("p_tg", TG_BLUE, 2.2, 1.1),
          dot("p_gt", "#dfe6ee", 2.2, 0.55, 3.5), dot("p_wa", WA_GREEN, 2.2, 0.4),
          dot("p_wa", WA_GREEN, 2.2, 1.5), dot("p_aw", "#dfe6ee", 2.2, 0.95, 3.5),
          dot("p_down", GREEN, 1.4, 0), dot("p_down", GREEN, 1.4, 0.7)]
    # phones
    o.append(phone(65, 125, 250, 430, "tgclip", "#0e1621", "#17212b", TG_BLUE, *s["tg_name"]))
    o.append(phone(885, 125, 250, 430, "waclip", "#0b141a", "#202c33", "#1f8f63", *s["wa_name"]))
    o.append(bubbles("tg", s["tg"], 84, 296, 200, "#2b5278", "#182533", s["tg_buttons"]))
    o.append(bubbles("wa", s["wa"], 904, 1116, 200, "#005c4b", "#202c33", offset=0.65))
    # app badges on the phones
    o.append(f'<rect x="125" y="112" width="130" height="26" rx="13" fill="{TG_BLUE}"/>'
             + T(190, 130, "Telegram", 13.5, "#ffffff", 700, "middle"))
    o.append(f'<rect x="945" y="112" width="130" height="26" rx="13" fill="{WA_GREEN}"/>'
             + T(1010, 130, "WhatsApp", 13.5, "#06301c", 700, "middle"))
    # server and robot
    st, ss, sl = s["server"]
    o.append(f'<rect x="430" y="165" width="340" height="175" rx="16" fill="{CARD}" stroke="{CARD_LINE}"/>'
             f'<path d="M448 166.5 H752" stroke="{GREEN}" stroke-width="3" stroke-linecap="round"/>'
             f'<circle cx="466" cy="207" r="21" fill="{GREEN}" fill-opacity=".13" stroke="{GREEN}" stroke-opacity=".5"/>'
             + icon("server", 466, 207, GREEN) + T(498, 203, st, 19, TEXT, 700) + T(498, 225, ss, 13.5, MUTED)
             + pulse(748, 189, GREEN)
             + f'<line x1="446" y1="246" x2="754" y2="246" stroke="{CARD_LINE}"/>')
    for i, line in enumerate(sl):
        o.append(f'<circle cx="457" cy="{271 + i * 28}" r="3" fill="{GREEN}"/>' + T(470, 276 + i * 28, line, 14.5))
    rt, rs, rl = s["robot"]
    o.append(f'<rect x="460" y="425" width="280" height="110" rx="16" fill="{CARD}" stroke="{CARD_LINE}"/>'
             f'<path d="M478 426.5 H722" stroke="{BLUE}" stroke-width="3" stroke-linecap="round"/>'
             f'<circle cx="496" cy="465" r="21" fill="{BLUE}" fill-opacity=".13" stroke="{BLUE}" stroke-opacity=".5"/>'
             + icon("robot", 496, 465, BLUE) + T(528, 461, rt, 19, TEXT, 700) + T(528, 483, rs, 13.5, MUTED)
             + f'<circle cx="487" cy="511" r="3" fill="{BLUE}"/>' + T(500, 516, rl, 14.5))
    # shared rules
    rt2, rlines = s["rules"]
    o.append(f'<rect x="395" y="578" width="410" height="160" rx="16" fill="#18202b" stroke="#2a3445"/>')
    o.append(T(419, 610, rt2, 16, AMBER, 700))
    for i, line in enumerate(rlines):
        o.append(f'<circle cx="425" cy="{637 + i * 30}" r="3" fill="{AMBER}"/>' + T(438, 642 + i * 30, line, 14.5, "#d5dce6"))
    # roles
    for (bx, col, (title, lines)) in ((40, TG_BLUE, s["tg_role"]), (860, WA_GREEN, s["wa_role"])):
        o.append(f'<rect x="{bx}" y="578" width="300" height="168" rx="16" fill="{CARD}" stroke="{CARD_LINE}"/>')
        o.append(T(bx + 20, 608, title, 16, col, 700))
        for i, line in enumerate(lines):
            o.append(f'<circle cx="{bx + 25}" cy="{631 + i * 23}" r="2.6" fill="{col}"/>'
                     + T(bx + 36, 636 + i * 23, line, 14, "#cfd7e2"))
    return svg(w, h, lang, s["title"], s["desc"], "\n".join(o))


# ----------------------------------------------------------------------------- 5. mobile app (planned)
APP = {
    "en": {
        "title": "Mobile app", "badge": "PLANNED",
        "sub": "Drive the robot from its own camera, from anywhere.",
        "how": "How it will work",
        "steps": ["Live camera view from the robot",
                  "The joystick sends 1 s moves, renewed while you hold it",
                  "Via the brain over Tailscale, never direct to the robot",
                  "Stop always wins: stop > voice > remote > planner",
                  "Remote limits: slower speed, shorter moves",
                  "Releasing an E-stop needs a fresh photo and a confirm"],
        "hud": ("LIVE", "Tailscale · 38 ms", "82%", "0.8 m"),
        "pills": ("Stand", "Sit"),
        "flow_caption": "ONE JOYSTICK COMMAND",
        "nodes": [("Mobile app", "your phone"), ("Brain", "home server"), ("Gateway", "robot"),
                  ("Body", "legs + safety")],
        "edges": [("Tailscale",), ("MQTT", "+ mTLS"), ("one", "sender")],
        "note": "Design draft, not built yet. The safety rules it depends on already run in the gateway and the body.",
        "desc": "Mock-up of the planned mobile app: a live camera view with a joystick and a stop button, and the path a command takes to the robot.",
    },
    "ja": {
        "title": "モバイルアプリ", "badge": "開発予定",
        "sub": "ロボットのカメラを見ながら、どこからでも操作。",
        "how": "動作の仕組み（予定）",
        "steps": ["ロボットのカメラ映像をライブ表示",
                  "ジョイスティックは1秒ずつの移動を送信、押す間は継続",
                  "Tailscale経由でブレインへ。ロボットへ直接は送らない",
                  "停止が最優先：停止 > 音声 > 遠隔 > プランナー",
                  "遠隔操作は低速・短い移動に制限",
                  "非常停止の解除には新しい写真と確認が必要"],
        "hud": ("LIVE", "Tailscale · 38 ms", "82%", "0.8 m"),
        "pills": ("立つ", "座る"),
        "flow_caption": "ジョイスティック操作の流れ",
        "nodes": [("モバイルアプリ", "スマホ"), ("ブレイン", "ホームサーバー"), ("ゲートウェイ", "ロボット"),
                  ("ボディ", "脚と安全機能")],
        "edges": [("Tailscale",), ("MQTT", "+ mTLS"), ("唯一の", "送信元")],
        "note": "設計案（未実装）。必要な安全ルールは、すでにゲートウェイとボディで動いている。",
        "desc": "開発予定のモバイルアプリの画面案：カメラ映像、ジョイスティック、停止ボタン、そしてロボットまでの指令の流れ。",
    },
}


def mobile(lang):
    s = APP[lang]
    w, h = 1200, 650
    o = [T(48, 66, s["title"], 30, TEXT, 700)]
    bx = 48 + tw(s["title"], 30) + 16
    bw = tw(s["badge"], 12.5) + 26
    o.append(f'<rect x="{bx:.0f}" y="44" width="{bw:.0f}" height="26" rx="13" fill="{AMBER}" fill-opacity=".14" stroke="{AMBER}"/>')
    o.append(T(bx + bw / 2, 62, s["badge"], 12.5, AMBER, 700, "middle", ls="1.5"))
    o.append(T(48, 98, s["sub"], 16.5, MUTED))
    # landscape phone
    o.append('<defs><clipPath id="scr"><rect x="70" y="144" width="556" height="292" rx="26"/></clipPath>'
             '<linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#151b25"/>'
             '<stop offset="1" stop-color="#222b38"/></linearGradient>'
             '<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a3342"/>'
             '<stop offset="1" stop-color="#394456"/></linearGradient></defs>')
    o.append('<rect x="48" y="130" width="600" height="320" rx="44" fill="#0a0d12" stroke="#2a3240" stroke-width="2"/>')
    o.append('<circle cx="59" cy="290" r="4" fill="#1d2430"/>')
    vx, vy = 348, 250
    scene = ['<rect x="70" y="144" width="556" height="106" fill="url(#wall)"/>',
             '<rect x="70" y="250" width="556" height="186" fill="url(#floor)"/>']
    for bxp in range(-560, 1260, 80):
        scene.append(f'<line x1="{vx}" y1="{vy}" x2="{bxp}" y2="436" stroke="#46526a" stroke-width="1"/>')
    for k in range(6):
        scene.append(f'<line x1="70" x2="626" y1="252" y2="252" stroke="#56627a" stroke-width="1.4">'
                     f'<animate attributeName="y1" values="252;440" dur="2.4s" begin="-{k * 0.4:g}s" '
                     f'calcMode="spline" keyTimes="0;1" keySplines=".7 0 1 1" repeatCount="indefinite"/>'
                     f'<animate attributeName="y2" values="252;440" dur="2.4s" begin="-{k * 0.4:g}s" '
                     f'calcMode="spline" keyTimes="0;1" keySplines=".7 0 1 1" repeatCount="indefinite"/></line>')
    # an obstacle the LiDAR has marked
    scene.append('<polygon points="452,282 512,282 526,272 466,272" fill="#a5714d"/>'
                 '<polygon points="512,282 526,272 526,326 512,338" fill="#6e4a33"/>'
                 '<rect x="452" y="282" width="60" height="56" fill="#8a5a3c"/>')
    scene.append(f'<rect x="444" y="264" width="90" height="82" rx="6" fill="none" stroke="{AMBER}" '
                 f'stroke-width="2" stroke-dasharray="6 5"/>')
    scene.append(f'<rect x="458" y="232" width="62" height="24" rx="12" fill="#000" fill-opacity=".55" stroke="{AMBER}"/>'
                 + T(489, 249, s["hud"][3], 13, AMBER, 700, "middle"))
    # HUD
    scene.append('<rect x="70" y="144" width="556" height="40" fill="#000" fill-opacity=".38"/>')
    scene.append(f'<circle cx="96" cy="164" r="5" fill="{RED}"><animate attributeName="opacity" values="1;.2;1" '
                 f'dur="1.2s" repeatCount="indefinite"/></circle>' + T(108, 169, s["hud"][0], 12.5, "#ffffff", 700))
    scene.append(T(348, 169, s["hud"][1], 12.5, "#cdd6e2", None, "middle"))
    scene.append('<rect x="574" y="157" width="28" height="14" rx="3" fill="none" stroke="#cdd6e2" stroke-width="1.5"/>'
                 f'<rect x="577" y="160" width="18" height="8" rx="1.5" fill="{GREEN}"/>'
                 '<rect x="603" y="161" width="3" height="6" rx="1" fill="#cdd6e2"/>'
                 + T(566, 169, s["hud"][2], 12.5, "#cdd6e2", None, "end"))
    scene.append('<path d="M340 300 h16 M348 292 v16" stroke="#ffffff" stroke-opacity=".35" stroke-width="1.5"/>')
    # joystick
    scene.append('<circle cx="150" cy="370" r="48" fill="#000" fill-opacity=".38" stroke="#ffffff" stroke-opacity=".25" stroke-width="1.5"/>')
    for ang in (0, 90, 180, 270):
        scene.append(f'<path d="M150 330 l-6 8 h12 z" fill="#ffffff" fill-opacity=".35" transform="rotate({ang} 150 370)"/>')
    scene.append('<circle cx="150" cy="370" r="20" fill="#e8edf3" fill-opacity=".92">'
                 '<animateTransform attributeName="transform" type="translate" values="0 0;0 -26;14 -20;0 0" '
                 'keyTimes="0;.3;.7;1" dur="3s" repeatCount="indefinite"/></circle>')
    # stop button
    scene.append(f'<circle cx="552" cy="370" r="38" fill="none" stroke="{RED}" stroke-width="3">'
                 '<animate attributeName="r" values="38;54" dur="1.8s" repeatCount="indefinite"/>'
                 '<animate attributeName="opacity" values=".7;0" dur="1.8s" repeatCount="indefinite"/></circle>')
    scene.append(f'<circle cx="552" cy="370" r="38" fill="{RED}"/>' + T(552, 376, "STOP", 16, "#ffffff", 800, "middle"))
    for k, label in enumerate(s["pills"]):
        px = 262 + k * 92
        scene.append(f'<rect x="{px}" y="398" width="84" height="30" rx="15" fill="#000" fill-opacity=".42" '
                     f'stroke="#ffffff" stroke-opacity=".25"/>' + T(px + 42, 418, label, 13, "#e8edf3", 600, "middle"))
    o.append('<g clip-path="url(#scr)">' + "".join(scene) + "</g>")
    o.append('<rect x="70" y="144" width="556" height="292" rx="26" fill="none" stroke="#000" stroke-opacity=".6"/>')
    # steps
    o.append(T(690, 152, s["how"], 19, TEXT, 700))
    for i, step in enumerate(s["steps"]):
        y = 198 + i * 48
        o.append(f'<circle cx="704" cy="{y - 5}" r="13" fill="{AMBER}" fill-opacity=".14" stroke="{AMBER}" stroke-opacity=".7"/>')
        o.append(T(704, y, str(i + 1), 13, AMBER, 700, "middle"))
        o.append(T(728, y, step, 15, "#d5dce6"))
    # flow strip
    o.append(T(48, 494, s["flow_caption"], 12.5, DIM, 700, ls="2"))
    xs, nw, ny, nh = [48, 343, 637, 932], 220, 508, 64
    cols = [AMBER, GREEN, BLUE, ORANGE]
    flow_paths = []
    for i, ((title, sub), x, c) in enumerate(zip(s["nodes"], xs, cols)):
        o.append(f'<rect x="{x}" y="{ny}" width="{nw}" height="{nh}" rx="14" fill="{CARD}" stroke="{CARD_LINE}"/>'
                 f'<rect x="{x}" y="{ny + 14}" width="4" height="{nh - 28}" rx="2" fill="{c}"/>'
                 + T(x + 22, ny + 29, title, 16, TEXT, 700) + T(x + 22, ny + 49, sub, 13, MUTED))
        if i < 3:
            x0, x1 = x + nw + 8, xs[i + 1] - 8
            pid = f"f{i}"
            flow_paths.append(f'<path id="{pid}" d="M{x0} {ny + nh / 2} H{x1}"/>')
            o.append(f'<line x1="{x0}" y1="{ny + nh / 2}" x2="{x1}" y2="{ny + nh / 2}" stroke="#4a5870" '
                     f'stroke-width="2" marker-end="url(#arrow)"/>')
            o.append(dot(pid, c, 1.6, 0, 3.8))
            lab = s["edges"][i]
            mid = (x0 + x1) / 2
            o.append(T(mid, ny + nh / 2 - 9, lab[0], 11.5, MUTED, 600, "middle"))
            if len(lab) > 1:
                o.append(T(mid, ny + nh / 2 + 21, lab[1], 11.5, MUTED, 600, "middle"))
    o.append("<defs>" + "".join(flow_paths) + "</defs>")
    o.append(T(48, 618, s["note"], 14, MUTED))
    return svg(w, h, lang, s["title"], s["desc"], "\n".join(o))


def main() -> None:
    for lang in ("en", "ja"):
        for name, fn in (("banner", banner), ("architecture", architecture), ("robot", robot),
                         ("messaging", messaging), ("mobile-app", mobile)):
            (OUT / f"{name}.{lang}.svg").write_text(fn(lang), encoding="utf-8")
    print(f"wrote diagrams to {OUT}")


if __name__ == "__main__":
    main()
