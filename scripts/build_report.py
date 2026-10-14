#!/usr/bin/env python3
"""Assemble one ticker's run into a single report: complete_report.md, and
complete_report.html (self-contained: no scripts, no external assets) when the
markdown-it-py package is available.

  build_report.py --results-dir R [--instrument-name NAME]

The report opens with what produced it: date, plugin version, instrument,
analysts, debate rounds and data sources. Sections that were not produced in this
run say so instead of appearing empty.
"""

import argparse
import glob
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSTS = [("Market analyst", "market_report.md"), ("Social sentiment analyst", "sentiment_report.md"),
            ("News analyst", "news_report.md"), ("Fundamentals analyst", "fundamentals_report.md")]
SOURCES = ("Yahoo Finance (prices, fundamentals, insider trades), SEC EDGAR (statements as filed), "
           "Google News RSS (company and macro headlines), Reddit RSS (retail discussion), "
           "FRED (macro indicators), Polymarket (event odds)")


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _json(path: str) -> dict | None:
    text = _read(path)
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


SPEAKING_ORDER = {"bull": 0, "bear": 1, "aggressive": 0, "conservative": 1, "neutral": 2}


def _turns(directory: str) -> list[tuple[str, str]]:
    """Turns in the order they were spoken: by round, then by each round's speaking order."""
    def order(path):
        side, _, rnd = os.path.basename(path)[:-3].rpartition("_")
        return (int(rnd) if rnd.isdigit() else 0, SPEAKING_ORDER.get(side, 9), side)
    return [(os.path.basename(p)[:-3], _demote(_read(p) or ""))
            for p in sorted(glob.glob(os.path.join(directory, "*.md")), key=order)]


def _demote(text: str, by: int = 3) -> str:
    """Push an agent's own headings below the report's, so its '# Title' sits under its section."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            if line[hashes:hashes + 1] == " ":
                line = "#" * min(6, hashes + by) + line[hashes:]
        out.append(line)
    return "\n".join(out)


def _version() -> str:
    manifest = _json(os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")) or {}
    return manifest.get("version", "unknown")


def _fmt(v) -> str:
    return "not provided" if v in (None, "") else str(v)


def build(results_dir: str, instrument_name: str | None) -> str:
    results_dir = os.path.abspath(results_dir)
    trade_date = os.path.basename(results_dir)
    ticker = os.path.basename(os.path.dirname(results_dir))
    plan = _json(os.path.join(results_dir, "research_plan.json"))
    proposal = _json(os.path.join(results_dir, "trader_proposal.json"))
    decision = _json(os.path.join(results_dir, "portfolio_decision.json"))
    debate, risk = _turns(os.path.join(results_dir, "debate_turns")), _turns(os.path.join(results_dir, "risk_turns"))
    present = [label for label, f in ANALYSTS if _read(os.path.join(results_dir, f))]
    debate_rounds = max((int(n.rpartition("_")[2]) for n, _ in debate if n.rpartition("_")[2].isdigit()), default=0)
    risk_rounds = max((int(n.rpartition("_")[2]) for n, _ in risk if n.rpartition("_")[2].isdigit()), default=0)

    title = f"{ticker}{f' ({instrument_name})' if instrument_name else ''}"
    out = [f"# Trading analysis: {title}", "",
           f"- **Rating**: {decision['rating'] if decision else 'no decision in this run'}",
           f"- **Analysis date**: {trade_date}",
           f"- **Produced by**: TradingClawd {_version()}",
           f"- **Analysts**: {', '.join(present) or 'none'}",
           f"- **Debate rounds**: research {debate_rounds or 'not run'}, risk {risk_rounds or 'not run'}",
           f"- **Data sources**: {SOURCES}", ""]

    if decision:
        out += ["## Final decision (Portfolio Manager)", "",
                f"**Rating**: {decision.get('rating')}", "",
                f"**Executive summary**: {decision.get('executive_summary', '')}", "",
                f"**Price target**: {_fmt(decision.get('price_target'))} · **Time horizon**: {_fmt(decision.get('time_horizon'))}", "",
                "### Investment thesis", "", decision.get("investment_thesis", ""), ""]
    if proposal:
        out += ["## Trader proposal", "",
                f"**Action**: {proposal.get('action')} · **Entry**: {_fmt(proposal.get('entry_price'))} · "
                f"**Stop-loss**: {_fmt(proposal.get('stop_loss'))}", "",
                f"**Position sizing**: {_fmt(proposal.get('position_sizing'))}", "",
                proposal.get("reasoning", ""), ""]
    if plan:
        out += ["## Research plan (Research Manager)", "",
                f"**Recommendation**: {plan.get('recommendation')}", "",
                "### Rationale", "", plan.get("rationale", ""), "",
                "### Strategic actions", "", plan.get("strategic_actions", ""), ""]
    if risk:
        out += ["## Risk debate", ""]
        for name, text in risk:
            out += [f"### {name.replace('_', ' round ').capitalize()}", "", text, ""]
    if debate:
        out += ["## Research debate", ""]
        for name, text in debate:
            out += [f"### {name.replace('_', ' round ').capitalize()}", "", text, ""]
    out += ["## Analyst reports", ""]
    for label, f in ANALYSTS:
        text = _read(os.path.join(results_dir, f))
        out += [f"### {label}", "", _demote(text) if text else "_Not produced in this run._", ""]
    return "\n".join(out).rstrip() + "\n"


CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#5f6368; --line:#e3e3e3; --accent:#0b57d0; --code:#f5f5f7; }
@media (prefers-color-scheme: dark) { :root { --bg:#121212; --fg:#e8e8e8; --muted:#a0a0a0; --line:#333; --accent:#8ab4f8; --code:#1e1e1e; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 32px; max-width: 1180px; margin: 0 auto; padding: 24px 16px; }
nav { position: sticky; top: 16px; align-self: start; font-size: 14px; max-height: calc(100vh - 32px); overflow: auto; }
nav a { display: block; color: var(--muted); text-decoration: none; padding: 3px 0; }
nav a.h3 { padding-left: 12px; font-size: 13px; }
nav a:hover { color: var(--accent); }
main { min-width: 0; }
h1 { font-size: 28px; margin-top: 0; } h2 { border-top: 1px solid var(--line); padding-top: 20px; margin-top: 32px; }
table { border-collapse: collapse; display: block; overflow-x: auto; margin: 12px 0; }
th, td { border: 1px solid var(--line); padding: 4px 10px; text-align: left; vertical-align: top; }
code, pre { background: var(--code); border-radius: 4px; } pre { padding: 12px; overflow-x: auto; }
@media (max-width: 800px) { .layout { grid-template-columns: 1fr; } nav { position: static; max-height: none; } }
@media print { nav { display: none; } .layout { display: block; } }
"""


def to_html(markdown: str, title: str) -> str | None:
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    toc, used = [], set()

    def anchor(match):
        level, text = match.group(1), match.group(2)
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-") or "section"
        base, n = slug, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        if level in ("2", "3"):
            toc.append(f'<a class="h{level}" href="#{slug}">{re.sub(r"<[^>]+>", "", text)}</a>')
        return f'<h{level} id="{slug}">{text}</h{level}>'

    body = re.sub(r"<h([1-3])>(.*?)</h\1>", anchor, body)
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=\"layout\">"
            f"<nav>{''.join(toc)}</nav><main>{body}</main></div></body></html>\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results-dir", required=True)
    p.add_argument("--instrument-name", default="")
    args = p.parse_args()
    if not os.path.isdir(args.results_dir):
        die(f"no results directory at {args.results_dir}")
    markdown = build(args.results_dir, args.instrument_name or None)
    md_path = os.path.join(args.results_dir, "complete_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    written = [md_path]
    page = to_html(markdown, f"TradingClawd: {os.path.basename(os.path.dirname(os.path.abspath(args.results_dir)))}")
    if page:
        html_path = os.path.join(args.results_dir, "complete_report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page)
        written.append(html_path)
    print("written: " + ", ".join(written))


if __name__ == "__main__":
    main()
