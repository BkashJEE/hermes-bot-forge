#!/usr/bin/env python3
"""Render docs/feature-cards.png — the feature grid used in posts and the README.

    python3 docs/make-feature-cards.py docs/feature-cards.svg && rsvg-convert ... 

Cards are data: icon chip, title, two wrapped lines, one dot pill. Text is measured
by estimated advance width, so keep bodies under ~90 characters or they will wrap
onto a third line and collide with the pill.
"""
import html
import sys

W = 1200
PAD, GAP = 28, 24
COLS, ROWS = 2, 5
CW = (W - PAD * 2 - GAP) // COLS
CH = 330
H = PAD * 2 + ROWS * CH + (ROWS - 1) * GAP

ICONS = {
 "spark": '<path d="M20 4c3 12 5 14 17 17-12 3-14 5-17 17-3-12-5-14-17-17 12-3 14-5 17-17z"/>',
 "crew": '<circle cx="13" cy="14" r="7"/><circle cx="28" cy="12" r="6"/><path d="M2 38c0-8 5-13 11-13s11 5 11 13z"/><path d="M24 38c0-7 4-11 9-11s9 4 9 11z" opacity=".7"/>',
 "bell": '<path d="M22 3a4 4 0 014 4v1c7 2 11 8 11 15v7l4 6H3l4-6v-7c0-7 4-13 11-15V7a4 4 0 014-4z"/><path d="M16 39h12a6 6 0 01-12 0z"/>',
 "chat": '<path d="M5 9a5 5 0 015-5h24a5 5 0 015 5v18a5 5 0 01-5 5H18l-9 8v-8a4 4 0 01-4-4z"/>',
 "grid": '<rect x="4" y="4" width="16" height="16" rx="4"/><rect x="24" y="4" width="16" height="16" rx="4" opacity=".75"/><rect x="4" y="24" width="16" height="16" rx="4" opacity=".75"/><rect x="24" y="24" width="16" height="16" rx="4" opacity=".5"/>',
 "shield": '<path d="M22 3l16 6v13c0 11-7 18-16 21C13 40 6 33 6 22V9z"/>',
 "book": '<path d="M7 5h20a6 6 0 016 6v28H13a6 6 0 01-6-6z"/><path d="M13 39h24v-6H13a3 3 0 000 6z" opacity=".65"/>',
 "eye": '<path d="M22 9c10 0 18 7 21 13-3 6-11 13-21 13S4 28 1 22C4 16 12 9 22 9z"/><circle cx="22" cy="22" r="7" fill="#0C1220"/>',
}

CARDS = [
 {"brand": True},
 {"icon": "spark", "title": "One sentence, a whole Bot",
  "body": "Name, face, SOUL.md, memory, tools, routines and its own chat.",
  "pill": "Zero setup", "dot": "#34D399"},
 {"icon": "crew", "title": "Hire a whole crew",
  "body": "One call builds a lead plus three or four specialists, one job each.",
  "pill": "create_team", "dot": "#60A5FA"},
 {"icon": "bell", "title": "What's waiting on you",
  "body": "Every Bot blocked on something only you can do, and how long it has sat there.",
  "pill": "New in 0.11", "dot": "#A78BFA"},
 {"icon": "chat", "title": "Manage them by talking",
  "body": "Rename, retool, teach, copy or hide a Bot — in chat. No config files.",
  "pill": "13 more tools", "dot": "#60A5FA"},
 {"icon": "grid", "title": "Starters worth stealing",
  "body": "Chief of staff, morning brief, research digest, competitor watch, repo triage.",
  "pill": "5 templates", "dot": "#22D3EE"},
 {"icon": "shield", "title": "Its own sandbox",
  "body": "A Bot with a shell runs in a container instead of on your machine.",
  "pill": "Docker · Apptainer", "dot": "#34D399"},
 {"icon": "book", "title": "A journal, not a vibe",
  "body": "What it did, the evidence, the next step. Never credentials.",
  "pill": "Stays local", "dot": "#22D3EE"},
 {"icon": "eye", "title": "You see it thinking",
  "body": "A reaction lands on your own message when a Bot picks it up, and again when it ends.",
  "pill": "Hermes Desktop", "dot": "#A78BFA"},
]

BOT = ('<g fill="url(#skin)"><rect x="246" y="86" width="20" height="46" rx="10"/><circle cx="256" cy="84" r="26"/></g>'
       '<rect x="112" y="146" width="288" height="232" rx="70" fill="url(#skin)"/>'
       '<rect x="70" y="220" width="34" height="86" rx="17" fill="url(#skin)"/>'
       '<rect x="408" y="220" width="34" height="86" rx="17" fill="url(#skin)"/>'
       '<rect x="146" y="188" width="220" height="148" rx="54" fill="#0B1020"/>'
       '<circle cx="210" cy="258" r="27" fill="#F8FAFC"/><circle cx="302" cy="258" r="27" fill="#F8FAFC"/>'
       '<circle cx="216" cy="262" r="11" fill="#0B1020"/><circle cx="308" cy="262" r="11" fill="#0B1020"/>'
       '<path d="M214 302c12 14 72 14 84 0" fill="none" stroke="#F8FAFC" stroke-width="12" stroke-linecap="round"/>')


def wrap(text, width, size):
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) * size * 0.505 > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def card(x, y, c):
    s = [f'<g transform="translate({x},{y})">',
         f'<rect width="{CW}" height="{CH}" rx="26" fill="url(#card)" stroke="#232C42" stroke-width="2"/>']
    if c.get("brand"):
        s += [f'<g transform="translate(36,36) scale(0.205)"><rect width="512" height="512" rx="114" fill="#0E1524"/>{BOT}</g>',
              '<text x="36" y="188" font-size="46" font-weight="bold" fill="url(#skin)" letter-spacing="-1">Bot Forge</text>',
              '<text x="36" y="228" font-size="23" font-weight="bold" fill="#E2E8F0">Say it. It gets built.</text>',
              '<text x="36" y="272" font-size="20" fill="#8FA1BC">In the Hermes plugin catalog. Open source, MIT.</text>',
              '<rect x="36" y="292" width="430" height="44" rx="12" fill="#0B1220" stroke="#2A3550" stroke-width="2"/>',
              '<text x="56" y="321" font-size="19" font-family="JetBrainsMono Nerd Font, DejaVu Sans Mono" fill="#7DD3FC">hermes plugins install bot-forge</text>']
    else:
        s += ['<rect x="36" y="34" width="66" height="66" rx="18" fill="#141D30" stroke="#28334D" stroke-width="2"/>',
              f'<g transform="translate(47,45)" fill="url(#skin)">{ICONS[c["icon"]]}</g>',
              f'<text x="36" y="152" font-size="30" font-weight="bold" fill="#F1F5F9" letter-spacing="-0.4">{html.escape(c["title"])}</text>']
        for i, line in enumerate(wrap(c["body"], CW - 82, 21)):
            s.append(f'<text x="36" y="{190 + i * 30}" font-size="21" fill="#94A6C2">{html.escape(line)}</text>')
        pw = int(len(c["pill"]) * 10.2) + 52
        s += [f'<rect x="36" y="{CH - 68}" width="{pw}" height="40" rx="12" fill="#111C30" stroke="#2A3A57" stroke-width="2"/>',
              f'<circle cx="58" cy="{CH - 48}" r="6" fill="{c["dot"]}"/>',
              f'<text x="74" y="{CH - 41}" font-size="18" font-weight="bold" fill="#B8C7DE">{html.escape(c["pill"])}</text>']
    s.append("</g>")
    return "\n".join(s)


def main(path):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             'font-family="Liberation Sans, Inter, DejaVu Sans">',
             '<defs>',
             '<linearGradient id="card" x1="0" y1="0" x2="0.6" y2="1">'
             '<stop offset="0%" stop-color="#151E31"/><stop offset="100%" stop-color="#0B1120"/></linearGradient>',
             '<linearGradient id="skin" x1="0" y1="0" x2="1" y2="1">'
             '<stop offset="0%" stop-color="#A78BFA"/><stop offset="50%" stop-color="#60A5FA"/>'
             '<stop offset="100%" stop-color="#22D3EE"/></linearGradient>',
             '</defs>',
             f'<rect width="{W}" height="{H}" fill="#070B13"/>']
    for i, c in enumerate(CARDS):
        parts.append(card(PAD + (i % COLS) * (CW + GAP), PAD + (i // COLS) * (CH + GAP), c))
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/feature-cards.svg")
