"""Analysis Module

Handles graph analysis using GitHub Copilot CLI.
Constructs prompts from configuration and graph metadata.
"""
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
import yaml

from src.graph_inputs import GraphInput

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
    graphs: list[GraphInput],
    report_info: dict,
    focus_areas: list[str] | None = None
) -> str:
    """
    Build complete analysis prompt from configuration.
    
    Args:
        prompts_config: Loaded prompts.yaml config
        graphs: Named graph image files to analyze
        report_info: Report metadata dictionary
        focus_areas: Optional list of focus areas for custom analysis
    
    Returns:
        Complete formatted prompt string
    """
    # Match keys from prompts.yaml structure: analysis_prompt.system / analysis_prompt.user_template
    ap = prompts_config.get("analysis_prompt", {})
    # Use `or ""` so a null YAML value doesn't raise AttributeError on .strip()
    system_prompt = (ap.get("system") or "").strip()
    user_template = (ap.get("user_template") or "").strip()
    
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
    
    # Build report_info summary string (matches {report_info} in template)
    report_info_str = (
        f"Title: {report_info.get('title', 'Graph Analysis Report')}\n"
        f"Captured: {report_info.get('captured_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"
    )

    graph_list = "\n".join(
        f"    - Graph name: {graph.name}\n"
        f"      Image path: {graph.path}"
        for graph in graphs
    )

    # Build complete prompt - template variables match prompts.yaml placeholders
    full_prompt = f"""{system_prompt}

{user_template.format(
    report_info=report_info_str,
    graph_count=len(graphs),
    graph_list=graph_list,
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

    if proc.stdout is None:
        raise AnalysisError("Copilot process stdout pipe is unavailable")
    if proc.stderr is None:
        raise AnalysisError("Copilot process stderr pipe is unavailable")

    output_lines: list[str] = []
    loop = asyncio.get_running_loop()
    last_log_time = loop.time()
    log_interval = 15  # log heartbeat every 15s so user knows it's still running

    # Drain stderr concurrently so its OS pipe buffer never fills and blocks the
    # subprocess before stdout has closed — which would otherwise deadlock.
    stderr_future = asyncio.ensure_future(proc.stderr.read())

    # Stream stdout line by line without blocking the event loop
    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").rstrip()
            output_lines.append(line)

            # Log a heartbeat periodically so the user can see progress
            now = loop.time()
            if now - last_log_time >= log_interval:
                logger.info(f"  ⏳ Copilot still running... ({len(output_lines)} lines received so far)")
                last_log_time = now
    except asyncio.CancelledError:
        # Coroutine was cancelled (e.g. Ctrl+C) — kill the child process so it
        # doesn't linger as an orphan after the Python process exits.
        logger.warning("Analysis cancelled — terminating Copilot process")
        proc.kill()
        await proc.wait()
        raise

    # stdout is fully drained; collect stderr and wait for exit code
    stderr_bytes = await stderr_future
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


async def analyze_graphs(
    prompts_config_path: Path,
    graphs: list[GraphInput],
    report_info: dict,
    focus_areas: list[str] | None = None,
) -> str:
    """
    Main analysis function - FAILS FAST if Copilot CLI unavailable.

    Args:
        prompts_config_path: Path to prompts.yaml
        graphs: Named graph image files to analyze
        report_info: Report metadata
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
        graphs,
        report_info,
        focus_areas
    )

    logger.info(f"Built analysis prompt ({len(prompt)} chars)")

    # Invoke Copilot CLI asynchronously - waits until process exits naturally
    analysis = await invoke_copilot_cli(prompt)
    return analysis


async def analyze_cloudhealth_dashboard(
    prompts_config_path: Path,
    screenshot_paths: list[Path],
    dashboard_info: dict,
    focus_areas: list[str] | None = None,
) -> str:
    """Compatibility wrapper for the old CloudHealth report entrypoint."""
    graphs = [GraphInput(name=path.name, path=path) for path in screenshot_paths]
    report_info = {
        "title": dashboard_info.get("title", "Graph Analysis Report"),
        "captured_at": dashboard_info.get(
            "captured_at",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    }
    return await analyze_graphs(prompts_config_path, graphs, report_info, focus_areas)
