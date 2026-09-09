#!/usr/bin/env python3
"""Build and optionally deploy the sanitized IB knowledge website."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from rv_data import validate as validate_rv


SITE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SITE_DIR / "site.config.json"
FORBIDDEN_PUBLIC_TERMS = (
    "source.txt",
    "source_file",
    "source_sha256",
    "processed_at",
    "to text",
    ".pdf",
    ".xlsx",
    "chrome_profile",
    "browser_profiles",
)


def load_config() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    required = {
        "WebsiteTitle",
        "BaseUrl",
        "SourceRoot",
        "OutputDir",
        "IncludeForecast",
        "Visibility",
    }
    missing = required - config.keys()
    if missing:
        raise ValueError(f"site.config.json 缺少欄位：{', '.join(sorted(missing))}")
    if config["Visibility"] != "public-sanitized":
        raise ValueError("公開網站只允許 Visibility=public-sanitized")
    return config


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("缺少 YAML front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("front matter 未正確結束")
    data: dict[str, str] = {}
    for raw in text[4:end].splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data, text[end + 5 :]


def remove_source_section(markdown: str) -> str:
    return re.split(r"(?m)^##\s+來源PDF\s*$", markdown, maxsplit=1)[0].rstrip()


def sanitize_tracker_markdown(markdown: str) -> str:
    """Keep Tracker meaning while removing internal source-storage wording."""
    return re.sub(
        r"舊sector與hyperscaler calls來源PDF未在To\s*Text",
        "舊sector與hyperscaler calls來源缺失",
        markdown,
        flags=re.IGNORECASE,
    )


def extract_section(markdown: str, title: str) -> str:
    pattern = rf"(?ms)^##\s+{re.escape(title)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, markdown)
    if not match:
        raise ValueError(f"缺少「{title}」章節")
    return match.group(1).strip()


def split_weekly(markdown: str) -> tuple[str, dict[str, str]]:
    clean = remove_source_section(markdown)
    key = extract_section(clean, "本週重點")
    key = re.split(r"(?m)^---\s*$", key, maxsplit=1)[0].strip()
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^##\s+\d+\.\s+(US IG|EU|HY)\s*$", clean))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
        sections[match.group(1)] = clean[match.end() : end].strip()
    missing = {"US IG", "EU", "HY"} - sections.keys()
    if missing:
        raise ValueError(f"Weekly 缺少市場章節：{', '.join(sorted(missing))}")
    return key, sections


def render_inline(value: str) -> str:
    escaped = html.escape(value, quote=False)
    placeholders: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        placeholders.append(f"<code>{match.group(1)}</code>")
        return f"@@CODE{len(placeholders) - 1}@@"

    escaped = re.sub(r"`([^`]+)`", stash_code, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((?:&lt;)?([^\s)&]+)(?:&gt;)?\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        escaped,
    )
    for index, code in enumerate(placeholders):
        escaped = escaped.replace(f"@@CODE{index}@@", code)
    return escaped


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").splitlines()
    output: list[str] = []
    index = 0
    paragraph: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{render_inline(' '.join(part.strip() for part in paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            index += 1
            continue
        if index + 1 < len(lines) and stripped.startswith("|") and is_table_separator(lines[index + 1]):
            flush_paragraph()
            close_list()
            headers = split_table_row(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(split_table_row(lines[index]))
                index += 1
            output.append('<div class="table-wrap"><table><thead><tr>')
            output.extend(f"<th>{render_inline(cell)}</th>" for cell in headers)
            output.append("</tr></thead><tbody>")
            for row in rows:
                output.append("<tr>")
                output.extend(f"<td>{render_inline(cell)}</td>" for cell in row)
                output.append("</tr>")
            output.append("</tbody></table></div>")
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)), 4)
            output.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if re.fullmatch(r"-{3,}", stripped):
            flush_paragraph()
            close_list()
            output.append("<hr>")
            index += 1
            continue
        item = re.match(r"^[-*]\s+(.+)$", stripped)
        ordered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if item or ordered:
            flush_paragraph()
            wanted = "ul" if item else "ol"
            if list_type != wanted:
                close_list()
                list_type = wanted
                output.append(f"<{wanted}>")
            content = (item or ordered).group(1)
            output.append(f"<li>{render_inline(content)}</li>")
            index += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            output.append(f"<blockquote>{render_inline(stripped.lstrip('>').strip())}</blockquote>")
            index += 1
            continue
        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    close_list()
    return "\n".join(output)


def plain_text(markdown: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_#>|-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(*parts: str) -> str:
    value = "-".join(parts).lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def parse_calls(markdown: str) -> dict[str, list[dict[str, str]]]:
    clean = remove_source_section(markdown)
    groups = {asset: [] for asset in ("US IG", "US HY", "EUR IG", "EUR HY")}
    section_matches = list(re.finditer(r"(?m)^##\s+(US IG|US HY|EUR)\s*$", clean))
    for section_index, match in enumerate(section_matches):
        section_name = match.group(1)
        end = section_matches[section_index + 1].start() if section_index + 1 < len(section_matches) else len(clean)
        lines = clean[match.end() : end].splitlines()
        for line_index in range(len(lines) - 1):
            if not lines[line_index].strip().startswith("|") or not is_table_separator(lines[line_index + 1]):
                continue
            headers = split_table_row(lines[line_index])
            row_index = line_index + 2
            while row_index < len(lines) and lines[row_index].strip().startswith("|"):
                values = split_table_row(lines[row_index])
                record = dict(zip(headers, values))
                asset_name = record.get("資產", section_name)
                if asset_name == "EUR":
                    asset_name = record.get("資產", "")
                fields = [
                    record.get("Spread", "—"),
                    record.get("Gross Supply", "—"),
                    record.get("Overweight Sector", "—"),
                    record.get("Underweight Sector", "—"),
                    record.get("Hyperscaler issuance", "—"),
                ]
                if asset_name in groups and any(value.strip() not in {"", "—"} for value in fields):
                    has_carried = any("Carried" in value for value in fields)
                    has_latest = any(value.strip() not in {"", "—"} and "Carried" not in value for value in fields)
                    status = "Latest + Carried" if has_carried and has_latest else "Carried" if has_carried else "Latest"
                    record["Status"] = status
                    groups[asset_name].append(record)
                row_index += 1
            break
    return groups


CALL_FIELDS = (
    ("Spread", "Spread"),
    ("Gross Supply", "Gross Supply"),
    ("Overweight Sector", "Overweight Sector"),
    ("Underweight Sector", "Underweight Sector"),
    ("Hyperscaler issuance", "Hyperscaler Issuance"),
)


def normalize_call_text(value: str) -> str:
    return re.sub(
        r"\s+",
        "",
        value.replace("–", "-").replace("—", "-").replace("−", "-").lower(),
    )


def split_outside_parentheses(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in value:
        if character in "（(":
            depth += 1
        elif character in "）)" and depth:
            depth -= 1
        if character == separator and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(character)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def tracker_call_tokens(value: str, call_type: str) -> list[dict[str, str]]:
    if value.strip() in {"", "—"}:
        return []
    group_carried = re.search(r"均\s+Carried，\s*自\s*(\d{4}-\d{2}-\d{2})", value)
    cleaned = re.sub(r"[（(]均\s+Carried.*[）)]\s*$", "", value).strip()
    separator = "、" if call_type in {"Overweight Sector", "Underweight Sector"} else "；"
    tokens = []
    for segment in split_outside_parentheses(cleaned, separator):
        call = re.split(r"[（(]", segment, maxsplit=1)[0].strip()
        if not call:
            continue
        carried = re.search(r"Carried，\s*自\s*(\d{4}-\d{2}-\d{2})", segment)
        tokens.append(
            {
                "call": call,
                "segment": segment,
                "carried_from": (carried or group_carried).group(1) if (carried or group_carried) else "",
            }
        )
    return tokens


def active_ledger_calls(ledger: dict) -> list[dict[str, str]]:
    latest_coverage: dict[tuple[str, str], str] = {}
    for coverage in ledger.get("coverage", []):
        for asset in coverage.get("assets", []):
            key = (coverage["broker"], asset)
            latest_coverage[key] = max(latest_coverage.get(key, ""), coverage["report_date"])

    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for record in ledger.get("records", []):
        key = (record["broker"], record["asset"], record["series"])
        groups.setdefault(key, []).append(record)

    active: list[dict[str, str]] = []
    for (broker, asset, _series), records in groups.items():
        active_date = max(record["report_date"] for record in records)
        coverage_date = latest_coverage.get((broker, asset), active_date)
        for record in records:
            if record["report_date"] != active_date:
                continue
            active.append(
                {
                    **record,
                    "status": "Carried" if active_date < coverage_date else "Latest",
                }
            )
    return active


def attach_call_links(
    calls: dict[str, list[dict[str, str]]],
    ledger: dict,
    report_by_source: dict[str, dict],
) -> None:
    active = active_ledger_calls(ledger)
    for asset, records in calls.items():
        for record in records:
            broker = record.get("券商", "")
            linked_fields: dict[str, list[dict[str, str]]] = {}
            for tracker_field, ledger_type in CALL_FIELDS:
                tokens = tracker_call_tokens(record.get(tracker_field, "—"), ledger_type)
                items: list[dict[str, str]] = []
                for token in tokens:
                    token_call = normalize_call_text(token["call"])
                    candidates = [
                        item
                        for item in active
                        if item["broker"] == broker
                        and item["asset"] == asset
                        and item["type"] == ledger_type
                        and normalize_call_text(item["call"]) == token_call
                    ]
                    # Tracker may prefix a compact series label (for example
                    # "BBB-A") to the ledger call. Keep exact matching first,
                    # then allow the ledger call to appear as a complete suffix.
                    if not candidates:
                        candidates = [
                            item
                            for item in active
                            if item["broker"] == broker
                            and item["asset"] == asset
                            and item["type"] == ledger_type
                            and token_call.endswith(normalize_call_text(item["call"]))
                        ]
                    if token["carried_from"]:
                        candidates = [
                            item for item in candidates if item["report_date"] == token["carried_from"]
                        ]
                    if len(candidates) > 1:
                        segment = normalize_call_text(token["segment"])
                        target_matches = [
                            item
                            for item in candidates
                            if item.get("target_date")
                            and normalize_call_text(item["target_date"]) in segment
                        ]
                        if target_matches:
                            candidates = target_matches
                    if len(candidates) != 1:
                        raise ValueError(
                            "Call來源無法唯一對應："
                            f"{broker} | {asset} | {ledger_type} | {token['segment']} "
                            f"(matches={len(candidates)})"
                        )
                    source = candidates[0]
                    report = report_by_source.get(source["source_report"])
                    if report is None:
                        raise ValueError(
                            "Call來源沒有公開報告頁："
                            f"{broker} | {asset} | {source['source_report']}"
                        )
                    items.append(
                        {
                            # Keep the Tracker's user-facing qualifier (for
                            # example "BBB-A") while sourcing the URL and
                            # metadata from the matched ledger record.
                            "call": token["call"],
                            "target_date": source.get("target_date", ""),
                            "status": source["status"],
                            "note": source.get("note", ""),
                            "url": f"reports/{report['slug']}/index.html",
                        }
                    )
                linked_fields[tracker_field] = items
            record["CallItems"] = linked_fields


def render_call_list(items: list[dict[str, str]]) -> str:
    if not items:
        return '<span class="muted">—</span>'
    rendered = []
    for index, item in enumerate(items):
        target = (
            f'<span class="call-target">／{html.escape(item["target_date"])}</span>'
            if item["target_date"]
            else ""
        )
        status_label = "延續" if item["status"] == "Carried" else "最新"
        extra = " is-extra" if index >= 2 else ""
        title = f' title="{html.escape(item["note"], quote=True)}"' if item["note"] else ""
        rendered.append(
            f'<div class="call{extra}"><a data-call-link href="{html.escape(item["url"], quote=True)}"{title}>'
            f'<span class="call-value">{html.escape(item["call"])}</span>{target}'
            f'<span class="call-status call-status-{item["status"].lower()}">{status_label}</span></a></div>'
        )
    if len(items) > 2:
        extra_count = len(items) - 2
        rendered.append(
            f'<button class="call-toggle" type="button" data-call-toggle data-extra-count="{extra_count}" '
            f'aria-expanded="false">展開其餘 {extra_count} 項</button>'
        )
    return f'<div class="call-list" data-call-list>{"".join(rendered)}</div>'


def call_table_row(record: dict[str, str]) -> str:
    linked_fields = record["CallItems"]

    values = (
        render_call_list(linked_fields["Spread"]),
        render_call_list(linked_fields["Gross Supply"]),
        render_call_list(linked_fields["Overweight Sector"]),
        render_call_list(linked_fields["Underweight Sector"]),
        render_call_list(linked_fields["Hyperscaler issuance"]),
        render_inline(record.get("最新／延續說明", "—")),
    )
    cells = "".join(f"<td>{value}</td>" for value in values)
    return f"""
      <tr>
        <th scope="row">{html.escape(record.get('券商', ''))}</th>
        <td class="call-status-cell"><time datetime="{html.escape(record.get('Call 日期', ''), quote=True)}">{html.escape(record.get('Call 日期', ''))}</time><span class="status-pill">{html.escape(record['Status'])}</span></td>
        {cells}
      </tr>"""


def page_shell(
    config: dict,
    title: str,
    description: str,
    body: str,
    *,
    prefix: str = "",
    canonical_path: str = "",
    home: bool = False,
) -> str:
    site_title = config["WebsiteTitle"]
    base_url = config["BaseUrl"].rstrip("/")
    canonical = f"{base_url}/{canonical_path.lstrip('/')}" if base_url else ""
    canonical_tag = f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">' if canonical else ""
    social = ""
    if home and base_url and (SITE_DIR / "assets" / "og.png").exists():
        og_url = f"{base_url}/og.png"
        social = f"""
  <meta property="og:type" content="website">
  <meta property="og:title" content="{html.escape(title, quote=True)}">
  <meta property="og:description" content="{html.escape(description, quote=True)}">
  <meta property="og:image" content="{html.escape(og_url, quote=True)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(title, quote=True)}">
  <meta name="twitter:description" content="{html.escape(description, quote=True)}">
  <meta name="twitter:image" content="{html.escape(og_url, quote=True)}">"""
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(description, quote=True)}">
  <title>{html.escape(title)}｜{html.escape(site_title)}</title>
  {canonical_tag}{social}
  <link rel="stylesheet" href="{prefix}assets/site.css">
</head>
<body>
  <a class="skip-link" href="#main-content">跳到主要內容</a>
  <header class="site-header">
    <div class="nav-shell">
      <a class="brand" href="{prefix}index.html">{html.escape(site_title)}</a>
      <nav class="site-nav" aria-label="主要導覽">
        <a href="{prefix}index.html#weekly">Weekly Summary</a>
        <a href="{prefix}index.html#calls">券商觀點</a>
        <a href="{prefix}index.html#reports">報告知識庫</a>
        <a href="{prefix}rv/">RV 相對價值</a>
      </nav>
    </div>
  </header>
  {body}
  <footer class="site-footer"><span>公開摘要版｜資料僅供研究參考，不構成投資建議。</span><span>內容來源：已整理之券商研究摘要</span></footer>
  <script src="{prefix}assets/site.js" defer></script>
</body>
</html>"""


def load_content(source_root: Path) -> tuple[list[dict], list[dict], str, dict[str, list[dict[str, str]]]]:
    ledger = json.loads((source_root / ".forecast-calls.json").read_text(encoding="utf-8"))
    coverage = {entry["source_report"]: entry["assets"] for entry in ledger.get("coverage", [])}
    reports: list[dict] = []
    seen_slugs: set[str] = set()
    for path in sorted(source_root.glob("*/*.md")):
        if path.parent.name == "Weekly":
            continue
        relative = path.relative_to(source_root).as_posix()
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        required = {"broker", "report_title", "report_date"}
        if missing := required - frontmatter.keys():
            raise ValueError(f"{relative} 缺少欄位：{', '.join(sorted(missing))}")
        if relative not in coverage:
            raise ValueError(f"{relative} 缺少 asset coverage")
        public_body = remove_source_section(body)
        summary = extract_section(public_body, "重點摘要")
        topics = extract_section(public_body, "主題整理")
        if not topics:
            raise ValueError(f"{relative} 缺少主題整理")
        slug = slugify(frontmatter["broker"], frontmatter["report_title"], frontmatter["report_date"])
        if slug in seen_slugs:
            raise ValueError(f"報告網址重複：{slug}")
        seen_slugs.add(slug)
        reports.append(
            {
                "broker": frontmatter["broker"],
                "title": frontmatter["report_title"],
                "date": frontmatter["report_date"],
                "assets": coverage[relative],
                "summary": summary,
                "summary_text": plain_text(summary),
                "topics": topics,
                "slug": slug,
                "source_report": relative,
            }
        )
    reports.sort(key=lambda item: (item["date"], item["broker"], item["title"]), reverse=True)

    weekly: list[dict] = []
    for path in sorted((source_root / "Weekly").glob("Weekly Summary*.md")):
        match = re.fullmatch(r"Weekly Summary(\d{8})\.md", path.name)
        if not match:
            raise ValueError(f"Weekly 檔名不符規範：{path.name}")
        raw_date = match.group(1)
        date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        markdown = remove_source_section(path.read_text(encoding="utf-8"))
        key, sections = split_weekly(markdown)
        weekly.append({"date": date, "markdown": markdown, "key": key, "sections": sections})
    weekly.sort(key=lambda item: item["date"], reverse=True)
    if not weekly:
        raise ValueError("找不到 Weekly Summary")

    tracker_markdown = remove_source_section((source_root / "IB Forecast Tracker.MD").read_text(encoding="utf-8"))
    tracker_markdown = sanitize_tracker_markdown(tracker_markdown)
    tracker_markdown = "\n".join(
        line
        for line in tracker_markdown.splitlines()
        if ".xlsx" not in line.lower()
    ).strip()
    calls = parse_calls(tracker_markdown)
    attach_call_links(calls, ledger, {item["source_report"]: item for item in reports})
    return reports, weekly, tracker_markdown, calls


def build_home(config: dict, reports: list[dict], weekly: list[dict], calls: dict[str, list[dict[str, str]]], output: Path) -> None:
    latest = weekly[0]
    updated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    weekly_full = render_markdown(latest["markdown"])
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-{slugify(asset)}" aria-controls="panel-{slugify(asset)}" aria-selected="{str(index == 0).lower()}" tabindex="{0 if index == 0 else -1}">{html.escape(asset)}</button>'
        for index, asset in enumerate(("US IG", "US HY", "EUR IG", "EUR HY"))
    )
    panels = "".join(
        f'<div class="call-panel" role="tabpanel" id="panel-{slugify(asset)}" aria-labelledby="tab-{slugify(asset)}"{ "" if index == 0 else " hidden"}><div class="table-wrap calls-table-wrap"><table class="views-table"><caption class="sr-only">{html.escape(asset)} 券商 Calls 比較表</caption><thead><tr><th>券商</th><th>Call 日期</th><th>Spread</th><th>Gross Supply</th><th>Overweight</th><th>Underweight</th><th>Hyperscaler Issuance</th><th>最新／延續說明</th></tr></thead><tbody>{"".join(call_table_row(item) for item in calls[asset])}</tbody></table></div></div>'
        for index, asset in enumerate(("US IG", "US HY", "EUR IG", "EUR HY"))
    )
    brokers = sorted({item["broker"] for item in reports})
    broker_options = "".join(f'<option value="{html.escape(item, quote=True)}">{html.escape(item)}</option>' for item in brokers)
    report_cards = []
    for item in reports:
        excerpt = item["summary_text"][:210].rstrip() + ("…" if len(item["summary_text"]) > 210 else "")
        tags = "".join(f'<span class="tag">{html.escape(value)}</span>' for value in item["assets"])
        searchable = " ".join([item["broker"], item["title"], item["date"], *item["assets"], item["summary_text"]])
        report_cards.append(f"""
          <article class="report-card" data-report-card data-broker="{html.escape(item['broker'], quote=True)}" data-assets="{html.escape('|'.join(item['assets']), quote=True)}" data-date="{item['date']}" data-search="{html.escape(searchable, quote=True)}">
            <div class="card-meta"><span class="broker-pill">{html.escape(item['broker'])}</span><time datetime="{item['date']}">{item['date']}</time></div>
            <h3>{html.escape(item['title'])}</h3>
            <p>{html.escape(excerpt)}</p>
            <div class="tags">{tags}</div>
            <a class="card-link" href="reports/{quote(item['slug'])}/index.html" aria-label="閱讀 {html.escape(item['broker'])} {html.escape(item['title'])} 摘要">閱讀重點摘要 →</a>
          </article>""")
    body = f"""
  <main id="main-content" class="page-shell">
    <section class="intro-hero" aria-labelledby="site-intro-title">
      <span class="eyebrow">Broker Research Knowledge Base</span>
      <h1 id="site-intro-title">信用市場券商觀點，一頁掌握。</h1>
      <p class="intro-copy">彙整已驗證的券商報告、最新 Weekly Summary 與 house call，快速掌握市場方向與相對價值。</p>
      <p class="update-time">本次網站更新：{updated_at}｜報告 {len(reports)} 份｜Weekly {len(weekly)} 期</p>
    </section>

    <section id="weekly" class="section weekly-section">
      <div class="section-heading"><div><span class="eyebrow">Latest Weekly Summary</span><h2>本週市場重點</h2><p>截至 {latest['date']}｜整合本週券商觀點</p></div><a class="text-link" href="weekly/{latest['date']}/index.html">閱讀完整週報 →</a></div>
      <div class="weekly-highlights">{render_markdown(latest['key'])}</div>
      <details class="weekly-full-detail"><summary>展開完整 Weekly Summary</summary><div class="weekly-full-body">{weekly_full}</div></details>
      <div class="weekly-actions"><a class="button" href="weekly/{latest['date']}/index.html">閱讀完整本週摘要</a><a class="button button-ghost" href="weekly/index.html">查看歷史 Weekly</a></div>
    </section>

    <section id="calls" class="section">
      <div class="section-heading"><div><span class="eyebrow">Broker calls</span><h2>券商最新 Calls</h2><p>依市場快速比較目前有效的 Spread、供給與產業配置觀點。</p></div><a class="button button-ghost" href="forecast/index.html">完整 Forecast Tracker</a></div>
      <div class="call-shell"><div class="tab-list" role="tablist" aria-label="市場分類">{tabs}</div>{panels}</div>
    </section>

    <section id="reports" class="section">
      <div class="section-heading"><div><span class="eyebrow">Research library</span><h2>個別券商報告</h2><p>搜尋已整理的公開重點摘要；完整主題整理可於報告頁閱讀，來源檔案不對外發布。</p></div></div>
      <div class="filters" aria-label="報告篩選器">
        <div class="field field-search"><label for="report-search">關鍵字</label><input id="report-search" type="search" placeholder="搜尋券商、標題或摘要"></div>
        <div class="field"><label for="broker-filter">券商</label><select id="broker-filter"><option value="">全部券商</option>{broker_options}</select></div>
        <div class="field"><label for="asset-filter">資產</label><select id="asset-filter"><option value="">全部資產</option><option>US IG</option><option>US HY</option><option>EUR IG</option><option>EUR HY</option></select></div>
        <div class="field"><label for="date-from">起始日期</label><input id="date-from" type="date"></div>
        <div class="field"><label for="date-to">結束日期</label><input id="date-to" type="date"></div>
        <button id="filter-reset" class="button button-ghost" type="button">清除</button>
      </div>
      <div class="report-toolbar"><span id="report-count" aria-live="polite"></span><span>由新到舊</span></div>
      <div class="report-grid">{''.join(report_cards)}</div>
      <div id="report-empty" class="empty-state" hidden>找不到符合條件的報告，請調整篩選條件。</div>
    </section>
  </main>"""
    html_page = page_shell(
        config,
        "最新研究",
        "整合每週信用市場摘要、券商 Calls 與個別報告重點。",
        body,
        canonical_path="",
        home=True,
    )
    (output / "index.html").write_text(html_page, encoding="utf-8")


def build_secondary_pages(config: dict, reports: list[dict], weekly: list[dict], tracker: str, output: Path) -> None:
    for item in reports:
        directory = output / "reports" / item["slug"]
        directory.mkdir(parents=True, exist_ok=True)
        tags = "".join(f'<span class="tag">{html.escape(asset)}</span>' for asset in item["assets"])
        body = f"""
  <main id="main-content" class="page-shell article-shell">
    <a class="card-link" href="../../index.html#reports">← 返回報告庫</a>
    <header class="article-header"><span class="eyebrow">{html.escape(item['broker'])} research</span><h1>{html.escape(item['title'])}</h1><div class="article-meta"><time datetime="{item['date']}">{item['date']}</time>{tags}</div></header>
    <article class="prose report-prose"><section class="report-summary"><h2>重點摘要</h2>{render_markdown(item['summary'])}</section><section class="report-topics"><h2>主題整理</h2>{render_markdown(item['topics'])}</section></article>
  </main>"""
        page = page_shell(
            config,
            f"{item['broker']}｜{item['title']}｜{item['date']}",
            item["summary_text"][:155],
            body,
            prefix="../../",
            canonical_path=f"reports/{item['slug']}/",
        )
        (directory / "index.html").write_text(page, encoding="utf-8")

    weekly_index = output / "weekly"
    weekly_index.mkdir(parents=True, exist_ok=True)
    history = "".join(
        f'<a class="history-card" href="{item["date"]}/index.html"><div><strong>每週信用市場摘要</strong><span>{item["date"]}</span></div><span>閱讀 →</span></a>'
        for item in weekly
    )
    body = f'<main id="main-content" class="page-shell article-shell"><header class="article-header"><span class="eyebrow">Weekly archive</span><h1>歷史 Weekly Summary</h1><p>依日期瀏覽每週信用市場券商觀點。</p></header><div class="history-grid">{history}</div></main>'
    (weekly_index / "index.html").write_text(page_shell(config, "歷史 Weekly Summary", "歷史信用市場週報摘要。", body, prefix="../", canonical_path="weekly/"), encoding="utf-8")

    for item in weekly:
        directory = weekly_index / item["date"]
        directory.mkdir(parents=True, exist_ok=True)
        body = f'<main id="main-content" class="page-shell article-shell"><a class="card-link" href="../index.html">← 返回 Weekly 歷史</a><header class="article-header"><span class="eyebrow">Weekly summary</span><h1>每週信用市場摘要</h1><div class="article-meta"><time datetime="{item["date"]}">{item["date"]}</time></div></header><article class="prose">{render_markdown(item["markdown"])}</article></main>'
        (directory / "index.html").write_text(page_shell(config, f"Weekly Summary｜{item['date']}", f"{item['date']} 信用市場券商摘要。", body, prefix="../../", canonical_path=f"weekly/{item['date']}/"), encoding="utf-8")

    forecast_dir = output / "forecast"
    forecast_dir.mkdir(parents=True, exist_ok=True)
    body = f'<main id="main-content" class="page-shell"><a class="card-link" href="../index.html#calls">← 返回券商 Calls</a><header class="article-header"><span class="eyebrow">Forecast tracker</span><h1>IB Forecast Tracker</h1><p>目前有效的券商 house call 與延續觀點。</p></header><article class="prose">{render_markdown(tracker)}</article></main>'
    (forecast_dir / "index.html").write_text(page_shell(config, "IB Forecast Tracker", "目前有效的券商 Spread、供給與產業配置觀點。", body, prefix="../", canonical_path="forecast/"), encoding="utf-8")


def build_search_index(reports: list[dict], weekly: list[dict], tracker: str, output: Path) -> None:
    data = {
        "schema_version": 1,
        "reports": [
            {
                "broker": item["broker"],
                "title": item["title"],
                "date": item["date"],
                "assets": item["assets"],
                "summary": item["summary_text"],
                "url": f"reports/{item['slug']}/",
            }
            for item in reports
        ],
        "weekly": [
            {"date": item["date"], "text": plain_text(item["markdown"]), "url": f"weekly/{item['date']}/"}
            for item in weekly
        ],
        "forecast": {"text": plain_text(tracker), "url": "forecast/"},
    }
    (output / "search-index.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hash_public(output: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "site-manifest.json":
            digest.update(path.relative_to(output).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_public(output: Path, expected_reports: int, expected_weekly: int) -> None:
    required = [output / "index.html", output / "forecast" / "index.html", output / "weekly" / "index.html", output / "search-index.json", output / "rv/index.html", output / "assets/rv-data.json", output / "assets/rv.css", output / "assets/rv.js"]
    for path in required:
        if not path.is_file():
            raise ValueError(f"缺少網站輸出：{path.relative_to(output)}")
    report_pages = list((output / "reports").glob("*/index.html"))
    weekly_pages = list((output / "weekly").glob("*/index.html"))
    if len(report_pages) != expected_reports:
        raise ValueError(f"報告頁數不符：{len(report_pages)} != {expected_reports}")
    if len(weekly_pages) != expected_weekly:
        raise ValueError(f"Weekly 頁數不符：{len(weekly_pages)} != {expected_weekly}")
    home = (output / "index.html").read_text(encoding="utf-8")
    order = [home.find('id="weekly"'), home.find('id="calls"'), home.find('id="reports"')]
    if min(order) < 0 or order != sorted(order):
        raise ValueError("首頁區塊順序不是 Weekly、Calls、Reports")
    for path in output.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".html", ".json", ".js", ".css", ".txt"}:
            lower = path.read_text(encoding="utf-8").lower()
            for term in FORBIDDEN_PUBLIC_TERMS:
                if term in lower:
                    raise ValueError(f"公開輸出含禁止資訊 {term!r}：{path.relative_to(output)}")


def build_rv(config: dict, output: Path) -> None:
    snapshot = json.loads((SITE_DIR / 'assets/rv-data.json').read_text(encoding='utf-8'))
    validate_rv(snapshot)
    for name in ('rv.css', 'rv.js', 'rv-data.json'):
        shutil.copy2(SITE_DIR / 'assets' / name, output / 'assets' / name)
    controls = ''.join(f'<label><input type="radio" name="section" value="{s}" {"checked" if s == "Overview" else ""}><span>{s}</span></label>' for s in snapshot['sections'])
    metrics = ''.join(f'<label><input type="checkbox" name="metric" value="{m}" {"checked" if m == "Spread" else ""}><span>{m}</span></label>' for m in ('Spread','10Y','30Y','10s30s'))
    body = f'''<link rel="stylesheet" href="../assets/rv.css">
<main id="main-content" class="rv-shell">
  <div class="rv-heading"><div><p class="rv-kicker">INVESTMENT GRADE / RELATIVE VALUE</p><h1>RV 相對價值</h1></div><p class="rv-date">資料日期 <time datetime="{snapshot['date']}">{snapshot['date'].replace('-', '/')}</time><br><strong>2Y Horizon</strong> · 歷史快照，非即時行情</p></div>
  <div class="rv-controls"><fieldset><legend>產業分類</legend><div class="rv-options">{controls}</div></fieldset><fieldset><legend>比較指標 <small>可複選</small></legend><div class="rv-options">{metrics}</div></fieldset></div>
  <div class="rv-guide"><span><i class="range-key"></i>2Y Min–Max</span><span><i class="median-key"></i>中位數</span><span><i class="current-key"></i>目前值</span><span><i class="pct-key"></i>Percentile</span><small>移入、聚焦或點選資料點，只顯示該點數值</small></div>
  <p id="rv-status" role="status">正在載入資料…</p><div id="rv-charts" class="rv-grid"></div>
  <aside class="rv-note"><h2>如何閱讀</h2><p>Percentile 越高，代表利差相對自身 2 年歷史較寬，或 10s30s 曲線較陡；不直接代表買進評級。10s30s 為 30Y 與 10Y 利差之差。已選指標在各產業內依圖例順序並排，使用同一 bp 刻度；下方 percentile 共用 0–100% 刻度。</p><p>移到資料點才顯示該點數值（最多 6 位小數，排除浮點尾差）。缺值不補零。投影片標示備援以約數呈現。</p><a href="../index.html">返回券商報告知識庫</a></aside>
  <noscript>請啟用 JavaScript 以操作互動圖表。</noscript>
</main><div id="rv-tooltip" role="tooltip" hidden></div><script src="../assets/rv.js" defer></script>'''
    page = page_shell(config, 'RV 相對價值', 'IG 相對價值：2Y 歷史區間、目前值與 percentile。', body, prefix='../', canonical_path='rv/')
    page = page.replace('內容來源：已整理之券商研究摘要', '內容來源：RV Excel 快照／已核對投影片')
    (output/'rv').mkdir()
    (output/'rv/index.html').write_text(page, encoding='utf-8')


def build(config: dict) -> tuple[Path, dict]:
    source_root = (SITE_DIR / config["SourceRoot"]).resolve()
    output = (SITE_DIR / config["OutputDir"]).resolve()
    if not source_root.is_dir() or source_root.name != "Processed":
        raise ValueError(f"Processed 來源不存在：{source_root}")
    if output.parent != SITE_DIR:
        raise ValueError("OutputDir 必須位於 site 目錄內")
    reports, weekly, tracker, calls = load_content(source_root)
    temporary = SITE_DIR / f".public-build-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        (temporary / "assets").mkdir()
        shutil.copy2(SITE_DIR / "assets" / "site.css", temporary / "assets" / "site.css")
        shutil.copy2(SITE_DIR / "assets" / "site.js", temporary / "assets" / "site.js")
        og_path = SITE_DIR / "assets" / "og.png"
        if og_path.is_file():
            shutil.copy2(og_path, temporary / "og.png")
        (temporary / ".nojekyll").write_text("", encoding="utf-8")
        build_home(config, reports, weekly, calls, temporary)
        build_secondary_pages(config, reports, weekly, tracker, temporary)
        build_search_index(reports, weekly, tracker, temporary)
        build_rv(config, temporary)
        validate_public(temporary, len(reports), len(weekly))
        manifest = {
            "schema_version": 1,
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "visibility": config["Visibility"],
            "report_count": len(reports),
            "weekly_count": len(weekly),
            "forecast_included": bool(config["IncludeForecast"]),
            "content_sha256": hash_public(temporary),
            "validation": {"status": "PASS"},
        }
        (temporary / "site-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        backup = SITE_DIR / f".public-previous-{uuid.uuid4().hex}"
        if output.exists():
            output.rename(backup)
        temporary.rename(output)
        if backup.exists():
            shutil.rmtree(backup)
        return output, manifest
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def run_git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=SITE_DIR, text=True, capture_output=True, check=check)


def deploy(manifest: dict) -> None:
    if not (SITE_DIR / ".git").exists():
        raise RuntimeError("site 尚未連接 GitHub repo，請先完成首次 GitHub 設定。")
    remote = run_git(["remote", "get-url", "origin"], check=False)
    if remote.returncode != 0:
        raise RuntimeError("site 尚未設定 origin remote。")
    run_git(["add", "public", "assets", "publish.py", "rv_data.py", "scripts", "site.config.json", "README.md", "tests", ".github", ".gitignore"])
    changes = run_git(["diff", "--cached", "--quiet"], check=False)
    if changes.returncode == 0:
        print("網站內容沒有變更，不需發布。")
        return
    message = f"Publish knowledge base {manifest['built_at']}"
    run_git(["commit", "-m", message])
    pushed = run_git(["push", "origin", "HEAD"], check=False)
    if pushed.returncode != 0:
        raise RuntimeError("GitHub push 失敗；請確認登入或 token 後再試。\n" + pushed.stderr.strip())
    print("已推送至 GitHub，GitHub Pages 將開始部署。")


def write_log(message: str) -> None:
    log_dir = SITE_DIR.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"site_publish_{datetime.now().astimezone():%Y-%m-%d}.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="建置券商報告知識庫網站")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build-only", action="store_true", help="只建置公開網站")
    mode.add_argument("--deploy", action="store_true", help="建置後 commit 並推送 GitHub")
    args = parser.parse_args()
    try:
        config = load_config()
        output, manifest = build(config)
        write_log(f"BUILD PASS reports={manifest['report_count']} weekly={manifest['weekly_count']} sha256={manifest['content_sha256']}")
        print(f"網站建置完成：{output}")
        print(f"報告 {manifest['report_count']} 份，Weekly {manifest['weekly_count']} 份，驗證 PASS")
        if args.deploy:
            deploy(manifest)
        return 0
    except Exception as exc:
        write_log(f"FAILED {exc}")
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
