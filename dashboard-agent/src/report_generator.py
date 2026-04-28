"""Report Generator Module

Handles HTML report generation from analysis markdown and graph images.
Uses Jinja2-style template substitution.
"""
import html
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from src.graph_inputs import GraphInput

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


def _sanitize_graph_filename(name: str, suffix: str) -> str:
    """Return a filesystem-safe filename fragment for a graph display name."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._-")
    if not slug:
        slug = "graph"
    return f"{slug}{suffix}"


def _copy_graph_images(graphs: list[GraphInput], graphs_dir: Path) -> dict[str, str]:
    """
    Copy graph images to the report assets directory with stable sanitized names.

    Returns a display-name-to-copied-filename mapping used when rendering tables.
    """
    image_map: dict[str, str] = {}
    for idx, graph in enumerate(graphs, start=1):
        suffix = graph.path.suffix or ".png"
        filename = f"{idx:03d}_{_sanitize_graph_filename(graph.name, suffix)}"
        shutil.copy2(graph.path, graphs_dir / filename)
        image_map[graph.name] = filename
        image_map[filename] = filename
        image_map[graph.path.name] = filename
    return image_map


def _embed_image(
    graph_label: str,
    graphs_dir: Path,
    rel_dir_name: str,
    graph_image_map: dict[str, str] | None = None,
) -> str:
    """
    Return an <img> tag referencing a graph image via a relative path.

    Falls back to a text span if the graph label cannot be mapped to an image.
    """
    # Strip backtick/code formatting Copilot sometimes wraps graph names with
    clean_label = graph_label.strip().strip("`")
    mapped_filename = graph_image_map.get(clean_label) if graph_image_map else None
    img_path = graphs_dir / mapped_filename if mapped_filename else graphs_dir / clean_label
    if not img_path.exists():
        # Fuzzy match: Copilot may have truncated or altered the label
        matches = sorted(graphs_dir.glob(f"*{Path(clean_label).stem}*"))
        img_path = matches[0] if matches else None

    if img_path and img_path.exists():
        rel_src = f"{rel_dir_name}/{img_path.name}"
        escaped_label = html.escape(clean_label)
        escaped_src = html.escape(rel_src, quote=True)
        return (
            f'<img src="{escaped_src}" class="graph-thumb" alt="{escaped_label}">'
            f'<span class="graph-filename">{escaped_label}</span>'
        )
    return f'<span class="graph-filename">{html.escape(clean_label)}</span>'


def _render_markdown_table(
    block: str,
    graphs_dir: Path | None = None,
    rel_dir_name: str = "",
    graph_image_map: dict[str, str] | None = None,
) -> str:
    """
    Convert a GFM markdown table block into an HTML <table>.

    Features:
    - First column (Graph) gets rowspan grouping: consecutive rows with the same
      graph label are merged into one cell so the graph image appears once.
    - When graphs_dir is provided, the first column shows the graph image
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
                graph_content = _embed_image(
                    row[0],
                    graphs_dir,
                    rel_dir_name,
                    graph_image_map,
                )
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
    graph_image_map: dict[str, str] | None = None,
) -> str:
    """
    Convert markdown to HTML.
    Supports headers, tables, lists, bold, italic, code blocks, inline code.

    Args:
        markdown_text: Raw markdown text from Copilot
        graphs_dir: Directory containing the saved graph image files
        rel_dir_name: Relative directory name used in <img src> attributes
        graph_image_map: Map of graph display names to copied graph filenames
    """
    table_placeholder = "\x00TABLE{}\x00"
    table_blocks: list[str] = []

    def extract_table(match: re.Match) -> str:
        idx = len(table_blocks)
        table_blocks.append(
            _render_markdown_table(
                match.group(0),
                graphs_dir,
                rel_dir_name,
                graph_image_map,
            )
        )
        return table_placeholder.format(idx)

    # A table block: consecutive lines starting with | that include a separator row.
    # The final row may be the end of the markdown string with no trailing newline.
    markdown_text = re.sub(
        r'(?m)(?:^\|.+\|\s*(?:\n|$))+',
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
            if not (
                para.startswith("\x00TABLE")
                or re.match(r'^<(?:h[1-6]|ul|pre|div|hr|table)', para)
            ):
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
    report_name: str,
    graph_count: int,
    content_html: str
) -> str:
    """
    Substitute Jinja2-style placeholders in template.
    
    Args:
        template: HTML template with {{placeholders}}
        timestamp: Report generation timestamp
        report_name: Name of report
        graph_count: Number of graphs analyzed
        content_html: Main analysis content (HTML)
    
    Returns:
        Complete HTML with substitutions
    """
    html = template
    html = html.replace("{{timestamp}}", timestamp)
    html = html.replace("{{report_name}}", report_name)
    html = html.replace("{{dashboard_name}}", report_name)
    html = html.replace("{{graph_count}}", str(graph_count))
    html = html.replace("{{screenshot_count}}", str(graph_count))
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
    report_info: dict,
    output_path: Path,
    graph_inputs: list[GraphInput] | None = None,
    screenshot_paths: list[Path] | None = None,
) -> Path:
    """
    Main report generation function.

    Args:
        template_path: Path to report_template.html
        analysis_markdown: Analysis text in markdown format
        report_info: Report metadata dictionary
        output_path: Where to save the HTML report
        graph_inputs: Named graph image files to embed
        screenshot_paths: Backward-compatible image paths without display names

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

        if graph_inputs is None:
            graph_inputs = [
                GraphInput(name=path.name, path=path)
                for path in (screenshot_paths or [])
            ]

        # Copy graph images to a permanent folder next to the report
        rel_dir_name = output_path.stem + "_graphs"
        graphs_dir = output_path.parent / rel_dir_name
        graphs_dir.mkdir(parents=True, exist_ok=True)
        graph_image_map = _copy_graph_images(graph_inputs, graphs_dir)
        logger.info(f"✓ Saved {len(graph_inputs)} graph files -> {graphs_dir.name}/")

        # Convert markdown to HTML using relative image paths
        content_html = markdown_to_html(
            clean_markdown,
            graphs_dir,
            rel_dir_name,
            graph_image_map,
        )
        
        # Prepare metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_name = report_info.get("title", "Graph Analysis Report")
        graph_count = len(graph_inputs)
        
        # Substitute placeholders
        final_html = substitute_template(
            template,
            timestamp,
            report_name,
            graph_count,
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
