"""Report Generator Module

Handles HTML report generation from analysis markdown and screenshots.
Uses Jinja2-style template substitution.
"""
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ReportGenerationError(Exception):
    """Raised when report generation fails."""
    pass


def strip_activity_preamble(text: str) -> str:
    """
    Remove Copilot CLI tool-activity output that appears before the actual markdown response.

    When run with --allow-all-tools, the CLI prints lines like:
        > Reading file: /path/to/screenshot.png
        Analyzing content...
    before the actual markdown analysis begins.

    Strategy: discard every line before the first markdown heading (# or ##).
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r'^#{1,6}\s', line.strip()):
            stripped = "\n".join(lines[i:])
            if len(lines) - i < len(lines):
                logger.info(f"Stripped {i} activity lines before analysis content")
            return stripped
    # No heading found — return as-is (let content render as-is)
    return text


def _embed_image(filename: str, graphs_dir: Path, rel_dir_name: str) -> str:
    """
    Return an <img> tag referencing the screenshot via a relative path.

    The file must already have been copied to graphs_dir by generate_html_report.
    Falls back to a text span if the file is not found (e.g. Copilot used a
    slightly different filename).
    """
    # Strip backtick/code formatting Copilot sometimes wraps filenames with
    clean_filename = filename.strip().strip("`")
    img_path = graphs_dir / clean_filename
    if not img_path.exists():
        # Fuzzy match: Copilot may have truncated or altered the name
        matches = sorted(graphs_dir.glob(f"*{Path(clean_filename).stem}*"))
        img_path = matches[0] if matches else None
    filename = clean_filename

    if img_path and img_path.exists():
        rel_src = f"{rel_dir_name}/{img_path.name}"
        return (
            f'<img src="{rel_src}" class="graph-thumb" alt="{filename}">'
            f'<span class="graph-filename">{img_path.name}</span>'
        )
    return f'<span class="graph-filename">{filename}</span>'


def _render_markdown_table(
    block: str,
    graphs_dir: Path | None = None,
    rel_dir_name: str = "",
) -> str:
    """
    Convert a GFM markdown table block into an HTML <table>.

    Features:
    - First column (Graph) gets rowspan grouping: consecutive rows with the same
      filename value are merged into one cell so the graph image appears once.
    - When graphs_dir is provided, the first column shows the actual screenshot
      via a relative <img src> path.
    """
    rows = [line.strip() for line in block.strip().splitlines() if line.strip()]
    if len(rows) < 2:
        return block

    def split_row(row: str) -> list[str]:
        return [cell.strip() for cell in row.strip("|").split("|")]

    header_cells = split_row(rows[0])
    body_rows = [split_row(r) for r in rows[2:]]  # skip separator row

    # Pad / trim every row to the header column count
    for i, row in enumerate(body_rows):
        while len(row) < len(header_cells):
            row.append("")
        body_rows[i] = row[:len(header_cells)]

    # Compute rowspan values for the first (Graph) column.
    # rowspan_info[i] == N  → this row starts a group of N rows (emit <td rowspan=N>)
    # rowspan_info[i] == 0  → this row's first cell is covered by a rowspan above (skip it)
    rowspan_info: list[int] = []
    i = 0
    while i < len(body_rows):
        val = body_rows[i][0]
        j = i + 1
        while j < len(body_rows) and body_rows[j][0] == val:
            j += 1
        span = j - i
        rowspan_info.append(span)
        rowspan_info.extend([0] * (span - 1))
        i = j

    thead = "<tr>" + "".join(f"<th>{c}</th>" for c in header_cells) + "</tr>"

    tbody_rows: list[str] = []
    for idx, row in enumerate(body_rows):
        span = rowspan_info[idx]
        if span == 0:
            # First cell covered by a rowspan above — only emit the data cells
            cells_html = "".join(f"<td>{cell}</td>" for cell in row[1:])
        else:
            rs_attr = f' rowspan="{span}"' if span > 1 else ""
            if graphs_dir:
                graph_content = _embed_image(row[0], graphs_dir, rel_dir_name)
            else:
                graph_content = f'<span class="graph-filename">{row[0]}</span>'
            graph_td = f'<td class="graph-cell"{rs_attr}>{graph_content}</td>'
            cells_html = graph_td + "".join(f"<td>{cell}</td>" for cell in row[1:])
        tbody_rows.append(f"<tr>{cells_html}</tr>")

    return (
        '<div class="table-wrapper">'
        f"<table><thead>{thead}</thead>"
        f"<tbody>{''.join(tbody_rows)}</tbody></table>"
        "</div>"
    )


def markdown_to_html(
    markdown_text: str,
    graphs_dir: Path | None = None,
    rel_dir_name: str = "",
) -> str:
    """
    Convert markdown to HTML.
    Supports headers, tables, lists, bold, italic, code blocks, inline code.

    Args:
        markdown_text: Raw markdown text from Copilot
        graphs_dir: Directory containing the saved graph PNG files
        rel_dir_name: Relative directory name used in <img src> attributes
    """
    table_placeholder = "\x00TABLE{}\x00"
    table_blocks: list[str] = []

    def extract_table(match: re.Match) -> str:
        idx = len(table_blocks)
        table_blocks.append(_render_markdown_table(match.group(0), graphs_dir, rel_dir_name))
        return table_placeholder.format(idx)

    # A table block: consecutive lines starting with | that include a separator row
    markdown_text = re.sub(
        r'(?m)^(\|.+\n)+',
        extract_table,
        markdown_text
    )

    html = markdown_text

    # Escape remaining HTML entities
    html = html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Code blocks (```)
    def replace_code_block(match: re.Match) -> str:
        code = match.group(1).replace("&lt;", "<").replace("&gt;", ">")
        return f'<pre><code>{code}</code></pre>'

    html = re.sub(r'```(?:\w+)?\n(.*?)```', replace_code_block, html, flags=re.DOTALL)

    # Inline code
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)

    # Horizontal rules (--- on its own line)
    html = re.sub(r'^-{3,}$', '<hr>', html, flags=re.MULTILINE)

    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

    # Bold and italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

    # Lists (unordered)
    lines = html.split('\n')
    in_list = False
    result_lines = []
    for line in lines:
        if re.match(r'^\s*[-]\s+', line):
            if not in_list:
                result_lines.append('<ul>')
                in_list = True
            item_text = re.sub(r'^\s*[-]\s+', '', line)
            result_lines.append(f'<li>{item_text}</li>')
        else:
            if in_list:
                result_lines.append('</ul>')
                in_list = False
            result_lines.append(line)
    if in_list:
        result_lines.append('</ul>')
    html = '\n'.join(result_lines)

    # Paragraphs
    paragraphs = re.split(r'\n\s*\n', html)
    formatted = []
    for para in paragraphs:
        para = para.strip()
        if para:
            if not re.match(r'^<(?:h[1-6]|ul|pre|div|hr|table)', para):
                para = f'<p>{para}</p>'
            formatted.append(para)
    html = '\n'.join(formatted)

    # Restore extracted tables
    for idx, table_html in enumerate(table_blocks):
        html = html.replace(table_placeholder.format(idx), table_html)

    # Process severity indicators
    html = process_severity_indicators(html)

    return html


def process_severity_indicators(html: str) -> str:
    """
    Convert severity indicator patterns to styled HTML.
    
    Patterns:
    - 🔴 or [CRITICAL] -> critical badge
    - ⚠️ or [WARNING] -> warning badge
    - ℹ️ or [INFO] -> info badge
    - ✅ or [POSITIVE] -> positive badge
    """
    # Replace emoji indicators
    html = html.replace('🔴', '<span class="severity-indicator critical">CRITICAL</span>')
    html = html.replace('⚠️', '<span class="severity-indicator warning">WARNING</span>')
    html = html.replace('ℹ️', '<span class="severity-indicator info">INFO</span>')
    html = html.replace('✅', '<span class="severity-indicator positive">POSITIVE</span>')
    
    # Replace text indicators
    html = re.sub(r'\[CRITICAL\]', '<span class="severity-indicator critical">CRITICAL</span>', html)
    html = re.sub(r'\[WARNING\]', '<span class="severity-indicator warning">WARNING</span>', html)
    html = re.sub(r'\[INFO\]', '<span class="severity-indicator info">INFO</span>', html)
    html = re.sub(r'\[POSITIVE\]', '<span class="severity-indicator positive">POSITIVE</span>', html)
    
    return html


def load_template(template_path: Path) -> str:
    """Load HTML template from file."""
    try:
        return template_path.read_text()
    except Exception as e:
        raise ReportGenerationError(f"Failed to load template: {e}")


def substitute_template(
    template: str,
    timestamp: str,
    dashboard_name: str,
    screenshot_count: int,
    content_html: str
) -> str:
    """
    Substitute Jinja2-style placeholders in template.
    
    Args:
        template: HTML template with {{placeholders}}
        timestamp: Report generation timestamp
        dashboard_name: Name of dashboard
        screenshot_count: Number of screenshots captured
        content_html: Main analysis content (HTML)
    
    Returns:
        Complete HTML with substitutions
    """
    html = template
    html = html.replace("{{timestamp}}", timestamp)
    html = html.replace("{{dashboard_name}}", dashboard_name)
    html = html.replace("{{screenshot_count}}", str(screenshot_count))
    html = html.replace("{{content}}", content_html)
    return html


def save_report(html: str, output_path: Path) -> None:
    """Save HTML report to file."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"✓ Report saved: {output_path}")
    except Exception as e:
        raise ReportGenerationError(f"Failed to save report: {e}")


def generate_html_report(
    template_path: Path,
    analysis_markdown: str,
    dashboard_info: dict,
    screenshot_paths: list[Path],
    output_path: Path
) -> Path:
    """
    Main report generation function.

    Args:
        template_path: Path to report_template.html
        analysis_markdown: Analysis text in markdown format
        dashboard_info: Dashboard metadata dictionary
        screenshot_paths: List of screenshot files (used for image embedding)
        output_path: Where to save the HTML report

    Returns:
        Path to generated report

    Raises:
        ReportGenerationError: If report generation fails
    """
    logger.info("Generating HTML report...")

    try:
        # Load template
        template = load_template(template_path)

        # Strip Copilot CLI activity preamble before converting
        clean_markdown = strip_activity_preamble(analysis_markdown)

        # Copy screenshots to a permanent folder next to the report
        rel_dir_name = output_path.stem + "_graphs"
        graphs_dir = output_path.parent / rel_dir_name
        graphs_dir.mkdir(parents=True, exist_ok=True)
        for src_path in screenshot_paths:
            shutil.copy2(src_path, graphs_dir / src_path.name)
        logger.info(f"✓ Saved {len(screenshot_paths)} graph files → {graphs_dir.name}/")

        # Convert markdown to HTML using relative image paths
        content_html = markdown_to_html(clean_markdown, graphs_dir, rel_dir_name)
        
        # Prepare metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dashboard_name = dashboard_info.get("title", "CloudHealth Dashboard")
        screenshot_count = len(screenshot_paths)
        
        # Substitute placeholders
        final_html = substitute_template(
            template,
            timestamp,
            dashboard_name,
            screenshot_count,
            content_html
        )
        
        # Save report
        save_report(final_html, output_path)
        
        logger.info("✓ Report generation complete")
        
        return output_path
        
    except ReportGenerationError:
        raise
    except Exception as e:
        raise ReportGenerationError(f"Unexpected error generating report: {e}")
