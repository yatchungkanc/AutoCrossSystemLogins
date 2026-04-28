"""CloudHealth Report Generator - Agent Orchestrator

Main entry point for automated CloudHealth dashboard analysis.
Coordinates screenshot capture, Copilot analysis, and HTML report generation.
"""
import asyncio
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Suppress Node.js deprecation warnings emitted by Playwright's internal
# Node.js server (e.g. DEP0169 url.parse). Must be set before the first
# async_playwright() call so the spawned Node process inherits it.
os.environ.setdefault("NODE_NO_WARNINGS", "1")

from playwright.async_api import async_playwright

# Import our modules
from src.screenshot_capture import (
    capture_cloudhealth_screenshots,
    verify_browser_connection,
    BrowserConnectionError,
    ScreenshotCaptureError
)
from src.analysis import (
    analyze_cloudhealth_dashboard,
    AnalysisError,
    CopilotUnavailableError
)
from src.report_generator import (
    generate_html_report,
    ReportGenerationError
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration paths
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "dashboard-agent" / "config"
OUTPUT_DIR = REPO_ROOT / "dashboard-agent" / "output"
TEMP_DIR = OUTPUT_DIR / "temp"

DASHBOARDS_CONFIG = CONFIG_DIR / "dashboards.yaml"
PROMPTS_CONFIG = CONFIG_DIR / "prompts.yaml"
REPORT_TEMPLATE = CONFIG_DIR / "report_template.html"

CDP_PORT = 9222


class ReportGenerationAgent:
    """Agent that orchestrates the entire report generation workflow."""
    
    def __init__(self, focus_areas: list[str] | None = None):
        self.focus_areas = focus_areas
        self.screenshot_paths: list[Path] = []
        self.dashboard_info: dict = {}
        self.temp_dir: Path | None = None
        self.report_path: Path | None = None
        
    async def run(self) -> Path:
        """
        Execute the complete report generation workflow.
        
        Returns:
            Path to generated HTML report
        """
        logger.info("╔════════════════════════════════════════╗")
        logger.info("║  CloudHealth Report Generator Agent   ║")
        logger.info("╚════════════════════════════════════════╝")
        
        try:
            # Step 1: Verify browser connection
            await self._verify_browser()
            
            # Step 2: Capture screenshots
            await self._capture_screenshots()
            
            # Step 3: Analyze with Copilot
            analysis_markdown = await self._analyze_dashboard()
            
            # Step 4: Generate HTML report
            await self._generate_report(analysis_markdown)
            
            # Step 5: Cleanup temporary files
            self._cleanup_temp_files()
            
            # Step 6: Open in browser
            await self._open_report()
            
            logger.info("")
            logger.info("╔════════════════════════════════════════╗")
            logger.info("║     ✓ Report Generation Complete      ║")
            logger.info("╚════════════════════════════════════════╝")
            logger.info(f"Report: {self.report_path}")
            
            return self.report_path
            
        except KeyboardInterrupt:
            logger.warning("\n⚠️  Operation cancelled by user")
            self._cleanup_temp_files()
            sys.exit(1)
        except Exception as e:
            logger.error(f"\n✗ Fatal error: {e}")
            self._cleanup_temp_files()
            raise
    
    async def _verify_browser(self):
        """Step 1: Verify browser session is active."""
        logger.info("")
        logger.info("┌─ Step 1: Verify Browser Connection")
        
        if not await verify_browser_connection(CDP_PORT):
            raise BrowserConnectionError(
                "No browser session found on CDP port {CDP_PORT}. "
                "Run: python -m src.orchestrator"
            )
        
        logger.info("└─ ✓ Browser session active")
    
    async def _capture_screenshots(self):
        """Step 2: Capture CloudHealth dashboard screenshots."""
        logger.info("")
        logger.info("┌─ Step 2: Capture Dashboard Screenshots")
        
        try:
            # Create temp directory with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.temp_dir = TEMP_DIR / f"capture_{timestamp}"
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            self.screenshot_paths, self.dashboard_info = await capture_cloudhealth_screenshots(
                DASHBOARDS_CONFIG,
                self.temp_dir,
                CDP_PORT
            )
            
            logger.info(f"└─ ✓ Captured {len(self.screenshot_paths)} screenshots")
            
        except BrowserConnectionError as e:
            logger.error(f"└─ ✗ Browser connection failed: {e}")
            raise
        except ScreenshotCaptureError as e:
            logger.error(f"└─ ✗ Screenshot capture failed: {e}")
            raise
    
    async def _analyze_dashboard(self) -> str:
        """Step 3: Analyze dashboard with GitHub Copilot CLI."""
        logger.info("")
        logger.info("┌─ Step 3: Analyze with GitHub Copilot CLI")
        
        # This will raise exception if Copilot CLI fails - FAIL FAST
        analysis_markdown = await analyze_cloudhealth_dashboard(
            PROMPTS_CONFIG,
            self.screenshot_paths,
            self.dashboard_info,
            self.focus_areas,
        )
        
        logger.info("└─ ✓ Analysis completed successfully")
        return analysis_markdown
    
    async def _generate_report(self, analysis_markdown: str):
        """Step 4: Generate HTML report from analysis."""
        logger.info("")
        logger.info("┌─ Step 4: Generate HTML Report")
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"cloudhealth_report_{timestamp}.html"
            report_output_path = OUTPUT_DIR / output_filename
            
            self.report_path = generate_html_report(
                REPORT_TEMPLATE,
                analysis_markdown,
                self.dashboard_info,
                report_output_path,
                screenshot_paths=self.screenshot_paths,
            )
            
            logger.info(f"└─ ✓ Report generated: {self.report_path.name}")
            
        except ReportGenerationError as e:
            logger.error(f"└─ ✗ Report generation failed: {e}")
            raise
    
    def _cleanup_temp_files(self):
        """Step 5: Cleanup temporary screenshot directory."""
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info("")
                logger.info("┌─ Step 5: Cleanup Temporary Files")
                logger.info(f"└─ ✓ Removed {self.temp_dir}")
            except Exception as e:
                logger.warning(f"⚠  Failed to cleanup temp files: {e}")
    
    async def _open_report(self):
        """Step 6: Open report in browser."""
        logger.info("")
        logger.info("┌─ Step 6: Open Report in Browser")
        
        try:
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                context = browser.contexts[0]
                
                # Open in new tab
                page = await context.new_page()
                await page.goto(f"file://{self.report_path.absolute()}")
                
                logger.info("└─ ✓ Report opened in browser")
                
                # Don't close browser
                browser.close = lambda: asyncio.sleep(0)
            finally:
                await pw.stop()
                
        except Exception as e:
            logger.warning(f"└─ ⚠  Could not auto-open browser: {e}")
            logger.info(f"   Manually open: {self.report_path}")


async def main(focus_area: str = ""):
    """
    Main entry point for CloudHealth report generation.
    
    Args:
        focus_area: Optional focus area for custom analysis (comma-separated if multiple)
    """
    # Parse focus areas
    focus_areas = None
    if focus_area:
        focus_areas = [area.strip() for area in focus_area.split(",")]
        logger.info(f"Focus areas: {', '.join(focus_areas)}")
    
    # Create and run agent
    agent = ReportGenerationAgent(focus_areas=focus_areas)
    try:
        await agent.run()
    except BrowserConnectionError as e:
        logger.error("")
        logger.error("═" * 60)
        logger.error("FATAL: Browser connection failed")
        logger.error(f"Reason: {e}")
        logger.error("")
        logger.error("Required action: python -m src.orchestrator")
        logger.error("═" * 60)
        sys.exit(1)
    except CopilotUnavailableError as e:
        logger.error("")
        logger.error("═" * 60)
        logger.error("FATAL: GitHub Copilot CLI not available")
        logger.error(f"Reason: {e}")
        logger.error("")
        logger.error("Install Copilot CLI:")
        logger.error("  • Via GitHub CLI: gh extension install github/gh-copilot")
        logger.error("  • Or download: https://github.com/github/copilot-cli")
        logger.error("═" * 60)
        sys.exit(1)
    except AnalysisError as e:
        logger.error("")
        logger.error("═" * 60)
        logger.error("FATAL: Analysis failed")
        logger.error(f"Reason: {e}")
        logger.error("")
        logger.error("This could be due to:")
        logger.error("  • Copilot CLI timeout (analysis took >120s)")
        logger.error("  • Copilot CLI returned an error")
        logger.error("  • Network connectivity issues")
        logger.error("═" * 60)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Agent failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    focus_area = sys.argv[1] if len(sys.argv) > 1 else ""
    asyncio.run(main(focus_area))
