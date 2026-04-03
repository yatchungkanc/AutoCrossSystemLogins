"""Analysis Module

Handles CloudHealth dashboard analysis using GitHub Copilot CLI.
Constructs prompts from configuration and screenshot metadata.
"""
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Raised when analysis fails."""
    pass


class CopilotUnavailableError(AnalysisError):
    """Raised when Copilot CLI is not available."""
    pass


def load_prompts_config(config_path: Path) -> dict:
    """Load prompts configuration from YAML file."""
    try:
        return yaml.safe_load(config_path.read_text())
    except Exception as e:
        raise AnalysisError(f"Failed to load prompts config: {e}")


def build_analysis_prompt(
    prompts_config: dict,
    screenshot_paths: list[Path],
    dashboard_info: dict,
    focus_areas: list[str] | None = None
) -> str:
    """
    Build complete analysis prompt from configuration.
    
    Args:
        prompts_config: Loaded prompts.yaml config
        screenshot_paths: List of screenshot file paths
        dashboard_info: Dashboard metadata dictionary
        focus_areas: Optional list of focus areas for custom analysis
    
    Returns:
        Complete formatted prompt string
    """
    # Match keys from prompts.yaml structure: analysis_prompt.system / analysis_prompt.user_template
    ap = prompts_config.get("analysis_prompt", {})
    system_prompt = ap.get("system", "").strip()
    user_template = ap.get("user_template", "").strip()
    
    if not user_template:
        raise AnalysisError(
            "prompts.yaml is missing 'analysis_prompt.user_template'. "
            "Check config/prompts.yaml structure."
        )
    
    # Build focus instruction string
    if focus_areas:
        custom_template = prompts_config.get("focus_instructions", {}).get(
            "custom_template",
            "Focus area: {focus_area}"
        )
        focus_instruction = custom_template.format(focus_area=", ".join(focus_areas))
    else:
        focus_instruction = prompts_config.get("focus_instructions", {}).get(
            "default",
            "Provide comprehensive analysis of all visible data."
        )
    
    # Build dashboard_info summary string (matches {dashboard_info} in template)
    dashboard_info_str = (
        f"Title: {dashboard_info.get('title', 'CloudHealth Dashboard')}\n"
        f"URL: {dashboard_info.get('url', 'N/A')}\n"
        f"Captured: {dashboard_info.get('captured_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"
    )
    
    screenshot_dir = dashboard_info.get("screenshot_dir", "N/A")

    # List actual filenames so Copilot uses the exact names in the Graph column
    # (skips the full-page overview so per-graph crops are the focus)
    graph_files = [p for p in screenshot_paths if p.name != "000_full_page.png"]
    if not graph_files:
        graph_files = screenshot_paths  # fallback: include everything
    filename_list = "\n".join(f"    - {p.name}" for p in graph_files)

    # Build complete prompt - template variables match prompts.yaml placeholders
    full_prompt = f"""{system_prompt}

{user_template.format(
    dashboard_info=dashboard_info_str,
    screenshot_count=len(screenshot_paths),
    screenshot_dir=screenshot_dir,
    screenshot_filenames=filename_list,
    focus_instruction=focus_instruction,
)}"""
    
    return full_prompt.strip()


async def invoke_copilot_cli(prompt: str) -> str:
    """
    Invoke GitHub Copilot CLI asynchronously, streaming output until the process exits.

    Uses asyncio.create_subprocess_exec so the event loop is not blocked.
    Output is streamed line-by-line as Copilot writes it — no hard timeout.
    The process is awaited until it naturally completes.

    Args:
        prompt: Complete prompt text

    Returns:
        Full stdout from Copilot as a string

    Raises:
        CopilotUnavailableError: If the copilot binary is not found
        AnalysisError: If the process exits with a non-zero code or produces no output
    """
    if not shutil.which("copilot"):
        raise CopilotUnavailableError(
            "copilot binary not found in PATH. "
            "Install via: gh extension install github/gh-copilot"
        )

    cmd = ["copilot", "-p", prompt, "--allow-all-tools"]

    logger.info("Starting Copilot CLI process (streaming output until complete)...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise CopilotUnavailableError(
            "copilot binary not found. Install via: gh extension install github/gh-copilot"
        )

    output_lines: list[str] = []
    last_log_time = asyncio.get_event_loop().time()
    log_interval = 15  # log heartbeat every 15s so user knows it's still running

    # Stream stdout line by line without blocking the event loop
    assert proc.stdout is not None
    assert proc.stderr is not None
    async for raw_line in proc.stdout:
        line = raw_line.decode(errors="replace").rstrip()
        output_lines.append(line)

        # Log a heartbeat periodically so the user can see progress
        now = asyncio.get_event_loop().time()
        if now - last_log_time >= log_interval:
            logger.info(f"  ⏳ Copilot still running... ({len(output_lines)} lines received so far)")
            last_log_time = now

    # stdout is fully drained; collect stderr and wait for exit code
    stderr_bytes = await proc.stderr.read()
    stderr_text = stderr_bytes.decode(errors="replace").strip() if stderr_bytes else ""

    await proc.wait()

    if proc.returncode != 0:
        logger.error(f"Copilot CLI exited with code {proc.returncode}")
        if stderr_text:
            logger.error(f"stderr: {stderr_text}")
        raise AnalysisError(
            f"Copilot CLI exited with code {proc.returncode}. "
            f"stderr: {stderr_text or '(none)'}"
        )

    analysis_text = "\n".join(output_lines).strip()
    if not analysis_text:
        raise AnalysisError("Copilot CLI completed but returned no output")

    logger.info(f"✓ Analysis complete ({len(output_lines)} lines)")
    return analysis_text


async def analyze_cloudhealth_dashboard(
    prompts_config_path: Path,
    screenshot_paths: list[Path],
    dashboard_info: dict,
    focus_areas: list[str] | None = None,
) -> str:
    """
    Main analysis function - FAILS FAST if Copilot CLI unavailable.

    Args:
        prompts_config_path: Path to prompts.yaml
        screenshot_paths: List of screenshot paths
        dashboard_info: Dashboard metadata
        focus_areas: Optional custom focus areas

    Returns:
        Analysis markdown from Copilot CLI

    Raises:
        CopilotUnavailableError: If Copilot CLI not found
        AnalysisError: If analysis fails
    """
    # Load config
    prompts_config = load_prompts_config(prompts_config_path)

    # Build prompt
    prompt = build_analysis_prompt(
        prompts_config,
        screenshot_paths,
        dashboard_info,
        focus_areas
    )

    logger.info(f"Built analysis prompt ({len(prompt)} chars)")

    # Invoke Copilot CLI asynchronously - waits until process exits naturally
    analysis = await invoke_copilot_cli(prompt)
    return analysis
