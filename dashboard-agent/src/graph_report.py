"""Generic graph report orchestrator.

Accepts caller-provided graph image files, analyzes them with Copilot CLI, and
generates a portable HTML report.
"""
import argparse
import asyncio
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from src.analysis import (
    AnalysisError,
    CopilotUnavailableError,
    analyze_graphs,
)
from src.graph_inputs import GraphInput, GraphInputError, GraphSource, parse_graph_sources
from src.report_generator import generate_html_report, ReportGenerationError
from src.screenshot_capture import (
    BrowserConnectionError,
    ScreenshotCaptureError,
    capture_graphs_from_url,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "dashboard-agent" / "config"
OUTPUT_DIR = REPO_ROOT / "dashboard-agent" / "output"
TEMP_DIR = OUTPUT_DIR / "temp"

PROMPTS_CONFIG = CONFIG_DIR / "prompts.yaml"
REPORT_TEMPLATE = CONFIG_DIR / "report_template.html"
CDP_PORT = 9222


class GraphReportAgent:
    """Agent that orchestrates generic graph report generation."""

    def __init__(
        self,
        sources: list[GraphSource],
        title: str = "Graph Analysis Report",
        focus_areas: list[str] | None = None,
        cdp_port: int = CDP_PORT,
    ):
        self.sources = sources
        self.graphs: list[GraphInput] = []
        self.title = title
        self.focus_areas = focus_areas
        self.cdp_port = cdp_port
        self.temp_dir: Path | None = None
        self.report_path: Path | None = None

    async def run(self) -> Path:
        """Execute the graph analysis and report generation workflow."""
        logger.info("========================================")
        logger.info("Graph Report Generator Agent")
        logger.info("========================================")

        report_info = {
            "title": self.title,
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        try:
            self.graphs = await self._resolve_graph_inputs()
            analysis_markdown = await self._analyze_graphs(report_info)
            self._generate_report(analysis_markdown, report_info)
            self._cleanup_temp_files()
        except Exception:
            self._cleanup_temp_files()
            raise

        logger.info("")
        logger.info("Report generation complete")
        logger.info(f"Report: {self.report_path}")
        return self.report_path

    async def _resolve_graph_inputs(self) -> list[GraphInput]:
        logger.info("")
        logger.info("Step 1: Resolve graph inputs")

        graphs: list[GraphInput] = []
        url_sources = [source for source in self.sources if source.is_url]

        for source in self.sources:
            if source.path is not None:
                graphs.append(GraphInput(name=source.name, path=source.path))

        if url_sources:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.temp_dir = TEMP_DIR / f"graph_capture_{timestamp}"
            self.temp_dir.mkdir(parents=True, exist_ok=True)

        for source_index, source in enumerate(url_sources, start=1):
            source_dir = self.temp_dir / f"{source_index:03d}_{_slugify(source.name)}"
            captured_paths, _ = await capture_graphs_from_url(
                source.name,
                source.url,
                source_dir,
                self.cdp_port,
            )
            graphs.extend(_name_captured_graphs(source.name, captured_paths))

        if not graphs:
            raise GraphInputError("No graph images were available for analysis.")

        seen_names: set[str] = set()
        for graph in graphs:
            key = graph.name.casefold()
            if key in seen_names:
                raise GraphInputError(f"Duplicate resolved graph name: {graph.name}")
            seen_names.add(key)

        logger.info(f"Resolved {len(graphs)} graph image(s) for analysis")
        return graphs

    async def _analyze_graphs(self, report_info: dict) -> str:
        logger.info("")
        logger.info("Step 2: Analyze graphs with GitHub Copilot CLI")
        analysis_markdown = await analyze_graphs(
            PROMPTS_CONFIG,
            self.graphs,
            report_info,
            self.focus_areas,
        )
        logger.info("Analysis completed successfully")
        return analysis_markdown

    def _generate_report(self, analysis_markdown: str, report_info: dict) -> None:
        logger.info("")
        logger.info("Step 3: Generate HTML report")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_output_path = OUTPUT_DIR / f"graph_report_{timestamp}.html"

        self.report_path = generate_html_report(
            REPORT_TEMPLATE,
            analysis_markdown,
            report_info,
            report_output_path,
            graph_inputs=self.graphs,
        )
        logger.info(f"Report generated: {self.report_path.name}")

    def _cleanup_temp_files(self) -> None:
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Removed temporary graph captures: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temporary graph captures: {e}")


def _parse_focus_values(values: list[str] | None) -> list[str] | None:
    """Parse repeated/comma-separated --focus values into a clean list."""
    if not values:
        return None

    focus_areas = [
        part.strip()
        for value in values
        for part in value.split(",")
        if part.strip()
    ]
    return focus_areas or None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return slug or "graph_source"


def _name_captured_graphs(source_name: str, paths: list[Path]) -> list[GraphInput]:
    if len(paths) == 1:
        return [GraphInput(name=source_name, path=paths[0])]

    return [
        GraphInput(name=f"{source_name} - Graph {idx}", path=path)
        for idx, path in enumerate(paths, start=1)
    ]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python run.py graph-report",
        description="Analyze one or more named graph image files or URLs and generate an HTML report.",
    )
    parser.add_argument(
        "--graph",
        action="append",
        default=[],
        metavar="NAME=PATH_OR_URL",
        help="Named graph image or URL to analyze. Repeat for multiple inputs.",
    )
    parser.add_argument(
        "--focus",
        action="append",
        metavar="TEXT",
        help="Optional focus area. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--title",
        default="Graph Analysis Report",
        help="Report title shown in the generated HTML.",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=CDP_PORT,
        help="CDP port for URL screenshot capture. Defaults to 9222.",
    )
    return parser


async def main(argv: list[str] | None = None) -> Path:
    """CLI entrypoint for generic graph report generation."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        sources = parse_graph_sources(args.graph)
        focus_areas = _parse_focus_values(args.focus)
        agent = GraphReportAgent(
            sources=sources,
            title=args.title.strip() or "Graph Analysis Report",
            focus_areas=focus_areas,
            cdp_port=args.cdp_port,
        )
        return await agent.run()
    except GraphInputError as e:
        parser.error(str(e))
    except BrowserConnectionError as e:
        logger.error("")
        logger.error("FATAL: Browser connection failed during URL capture")
        logger.error(f"Reason: {e}")
        logger.error("Required action: python run.py")
        sys.exit(1)
    except ScreenshotCaptureError as e:
        logger.error("")
        logger.error("FATAL: URL screenshot capture failed")
        logger.error(f"Reason: {e}")
        sys.exit(1)
    except CopilotUnavailableError as e:
        logger.error("")
        logger.error("FATAL: GitHub Copilot CLI not available")
        logger.error(f"Reason: {e}")
        logger.error("Install with: gh extension install github/gh-copilot")
        sys.exit(1)
    except AnalysisError as e:
        logger.error("")
        logger.error("FATAL: Analysis failed")
        logger.error(f"Reason: {e}")
        sys.exit(1)
    except ReportGenerationError as e:
        logger.error("")
        logger.error("FATAL: Report generation failed")
        logger.error(f"Reason: {e}")
        sys.exit(1)

    raise RuntimeError("unreachable")


if __name__ == "__main__":
    asyncio.run(main())
