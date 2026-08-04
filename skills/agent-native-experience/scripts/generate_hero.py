#!/usr/bin/env python3
"""Generate the deterministic, tracking-free Agent Native Experience hero."""

from pathlib import Path


OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "agent-native-experience.svg"
SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 480" role="img" aria-labelledby="title desc">
  <title id="title">Agent Native Experience</title>
  <desc id="desc">An evidence path from documentation through agent and human journeys to first value.</desc>
  <rect width="1200" height="480" rx="28" fill="#0b1020"/>
  <path d="M76 330 C250 330 250 154 424 154 S598 330 772 330 946 154 1120 154" fill="none" stroke="#5eead4" stroke-width="8"/>
  <g fill="#0b1020" stroke="#f8fafc" stroke-width="4">
    <circle cx="76" cy="330" r="24"/><circle cx="424" cy="154" r="24"/><circle cx="772" cy="330" r="24"/><circle cx="1120" cy="154" r="24"/>
  </g>
  <g fill="#f8fafc" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="22">
    <text x="48" y="386">DOCS</text><text x="377" y="108">AGENT</text><text x="731" y="386">HUMAN</text><text x="1036" y="108">VALUE</text>
  </g>
  <text x="72" y="76" fill="#f8fafc" font-family="system-ui, sans-serif" font-size="40" font-weight="700">Agent Native Experience</text>
  <text x="72" y="119" fill="#94a3b8" font-family="system-ui, sans-serif" font-size="22">Evidence over impressions. Activation over HTTP 200.</text>
</svg>
'''


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(SVG, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
