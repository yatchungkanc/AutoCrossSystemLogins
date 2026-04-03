"""Screenshot Capture Module

Handles connection to browser and systematic screenshot capture of CloudHealth dashboards.
Captures entire page with incremental scrolling to ensure all graphs are included.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright, Page
import yaml

logger = logging.getLogger(__name__)


class ScreenshotCaptureError(Exception):
    """Raised when screenshot capture fails."""
    pass


class BrowserConnectionError(Exception):
    """Raised when unable to connect to browser."""
    pass


async def verify_browser_connection(cdp_port: int = 9222) -> bool:
    """Verify that browser session is running and accessible."""
    logger.info("Verifying browser session...")
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
        logger.info("✓ Browser session is active")
        browser.close = lambda: asyncio.sleep(0)  # Don't close browser
        return True
    except Exception as e:
        logger.error(f"✗ Browser session not found: {e}")
        logger.error("Please run: python -m src.orchestrator")
        return False
    finally:
        await pw.stop()


async def capture_full_page(
    page: Page,
    output_dir: Path,
) -> list[Path]:
    """
    Capture the entire page content including inside scrollable containers (SPAs).

    CloudHealth renders content inside a scrollable inner div, not document.body.
    window.scrollTo / document.scrollHeight only see the outer shell (= viewport height).
    Strategy:
      1. Find the deepest element whose scrollHeight > clientHeight (the real container).
      2. Expand viewport to full scroll height of that container, wait for re-render.
      3. Take one full screenshot capturing everything.
      4. Restore original viewport.
    """
    screenshots = []

    # Inject JS helper: returns scrollHeight, clientHeight and a CSS selector
    # for the element with the most scrollable content.
    container_info = await page.evaluate("""() => {
        const candidates = [...document.querySelectorAll('*')].filter(el => {
            const style = window.getComputedStyle(el);
            const ov = style.overflow + ' ' + style.overflowY;
            const rect = el.getBoundingClientRect();
            return (ov.includes('auto') || ov.includes('scroll'))
                && el.scrollHeight > el.clientHeight + 50
                && rect.height > 200
                && rect.width > 200;
        });

        if (candidates.length === 0) {
            return {
                useDocument: true,
                scrollHeight: Math.max(document.body.scrollHeight,
                                       document.documentElement.scrollHeight),
                clientHeight: window.innerHeight,
                selector: null
            };
        }

        // Pick the candidate with the largest scrollHeight
        candidates.sort((a, b) => b.scrollHeight - a.scrollHeight);
        const el = candidates[0];
        // Build a selector robust enough to re-find the element
        const id = el.id ? '#' + el.id : '';
        const cls = el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : '';
        return {
            useDocument: false,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            selector: el.tagName.toLowerCase() + (id || cls)
        };
    }""")

    scroll_height = container_info["scroll_height"] if "scroll_height" in container_info else container_info.get("scrollHeight", 0)
    client_height = container_info["client_height"] if "client_height" in container_info else container_info.get("clientHeight", 0)
    use_document = container_info.get("useDocument", True)
    selector = container_info.get("selector")

    logger.info(f"Scroll container: {'document' if use_document else selector}")
    logger.info(f"Content height: {scroll_height}px  |  Visible height: {client_height}px")

    # --- Capture: expand viewport to full content height, screenshot, restore ---
    original_vp = page.viewport_size or {"width": 1920, "height": 1080}
    vp_width = original_vp["width"]

    # Set viewport tall enough to show all content
    try:
        await page.set_viewport_size({"width": vp_width, "height": scroll_height + 100})
    except Exception as e:
        raise ScreenshotCaptureError(f"Failed to resize viewport: {e}") from e
    await asyncio.sleep(2)  # Give charts time to re-render at new height

    full_page_path = output_dir / "000_full_page.png"
    try:
        await page.screenshot(path=str(full_page_path))
    except Exception as e:
        raise ScreenshotCaptureError(f"Failed to capture full-page screenshot: {e}") from e
    screenshots.append(full_page_path)
    size_kb = full_page_path.stat().st_size // 1024
    logger.info(f"  ✓ Full-page screenshot: {full_page_path.name} ({size_kb}KB, height={scroll_height}px)")

    # Collect chart bounding boxes BEFORE restoring the viewport — coordinates
    # are in the expanded document space and match pixels in full_page.png.
    boxes = await _collect_chart_boxes(page)

    # Restore original viewport
    await page.set_viewport_size(original_vp)
    await asyncio.sleep(1)

    # --- Crop one PNG per chart from the full-page image (no more live screenshots) ---
    if boxes:
        crops = _crop_graphs_from_full_page(full_page_path, boxes, output_dir)
        screenshots.extend(crops)
        logger.info(f"  ✓ Cropped {len(crops)} graphs from full-page image")
    else:
        # Fallback: viewport-strip crops from the full-page image
        logger.info("  No chart elements detected — falling back to viewport-strip crops")
        screenshots.extend(
            _crop_strip_sections(full_page_path, output_dir, client_height)
        )

    return screenshots


async def _collect_chart_boxes(page: Page) -> list[dict]:
    """
    Return de-duplicated bounding boxes of chart elements in document coordinates.

    Uses SVG/canvas element detection instead of CSS class names so it works
    regardless of the chart library or framework CloudHealth uses.

    Strategy:
    - Find every <svg> that is a chart root (large enough, not nested inside
      another <svg> element).
    - Walk up the DOM from each SVG to find the tightest wrapping container
      that still fits within WRAP_MARGIN px — this captures the chart title and
      legend that may live in HTML siblings of the SVG.
    - Also collect large <canvas> elements (canvas-based chart renderers).
    - De-duplicate by removing any box that completely contains a smaller box
      already in the result set (i.e. skip parent wrappers that accidentally
      matched multiple charts inside them).
    """
    boxes: list[dict] = await page.evaluate("""
        () => {
            const MIN_W = 150, MIN_H = 100;
            // How much larger than the SVG the wrapping container is allowed to be
            // per side (covers titles, legends, axis labels in HTML overlays).
            const WRAP_MARGIN = 120;
            const candidates = [];

            // ── SVG-based detection ──────────────────────────────────────────────
            for (const svg of document.querySelectorAll('svg')) {
                const sr = svg.getBoundingClientRect();
                if (sr.width < MIN_W || sr.height < MIN_H) continue;

                // Skip SVGs that are nested inside another SVG — those are
                // decorative sub-elements of a larger chart, not chart roots.
                if (svg.parentElement && svg.parentElement.closest('svg')) continue;

                // Walk up to find the tightest wrapping element (title + legend
                // may live in HTML siblings but share the same parent container).
                let container = svg;
                let el = svg.parentElement;
                while (el && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
                    const er = el.getBoundingClientRect();
                    const cr = container.getBoundingClientRect();
                    if (er.width  <= cr.width  + WRAP_MARGIN &&
                        er.height <= cr.height + WRAP_MARGIN) {
                        container = el;
                        el = el.parentElement;
                    } else {
                        break;
                    }
                }

                const r = container.getBoundingClientRect();
                candidates.push({
                    x:      r.left + window.scrollX,
                    y:      r.top  + window.scrollY,
                    width:  r.width,
                    height: r.height
                });
            }

            // ── Canvas-based detection ───────────────────────────────────────────
            for (const cv of document.querySelectorAll('canvas')) {
                const r = cv.getBoundingClientRect();
                if (r.width < MIN_W || r.height < MIN_H) continue;
                candidates.push({
                    x:      r.left + window.scrollX,
                    y:      r.top  + window.scrollY,
                    width:  r.width,
                    height: r.height
                });
            }

            // ── De-duplicate ─────────────────────────────────────────────────────
            // Sort by area ascending so leaf (smaller) elements are processed first.
            candidates.sort((a, b) => (a.width * a.height) - (b.width * b.height));

            function containedIn(inner, outer) {
                return inner.x >= outer.x - 20 &&
                       inner.y >= outer.y - 20 &&
                       inner.x + inner.width  <= outer.x + outer.width  + 20 &&
                       inner.y + inner.height <= outer.y + outer.height + 20;
            }

            const result = [];
            for (const c of candidates) {
                // Skip if c is a parent container of something already captured.
                if (result.some(r => containedIn(r, c))) continue;
                // Skip near-exact duplicates (same element seen via multiple paths).
                if (result.some(r => Math.abs(r.x - c.x) < 30 && Math.abs(r.y - c.y) < 30)) continue;
                result.push(c);
            }
            return result;
        }
    """)

    logger.info(f"  Found {len(boxes)} chart bounding boxes")
    return boxes


def _crop_graphs_from_full_page(
    full_page_path: Path,
    boxes: list[dict],
    output_dir: Path,
    padding: int = 8,
) -> list[Path]:
    """
    Crop each bounding box out of the full-page PNG.

    Args:
        full_page_path: Path to 000_full_page.png
        boxes: List of {x, y, width, height} dicts (document coordinates)
        output_dir: Directory to write cropped PNGs into
        padding: Extra pixels added on each side of the crop (default 8)

    Returns:
        List of paths to the cropped PNG files, in top-to-bottom order.
    """
    try:
        img = Image.open(full_page_path)
    except Exception as e:
        raise ScreenshotCaptureError(f"Failed to open full-page image {full_page_path}: {e}") from e
    img_w, img_h = img.size

    # Sort top-to-bottom so numbering matches visual order on the page
    sorted_boxes = sorted(boxes, key=lambda b: b["y"])

    crops: list[Path] = []
    for idx, b in enumerate(sorted_boxes, start=1):
        left   = max(0, int(b["x"]) - padding)
        top    = max(0, int(b["y"]) - padding)
        right  = min(img_w, int(b["x"] + b["width"]) + padding)
        bottom = min(img_h, int(b["y"] + b["height"]) + padding)

        if right <= left or bottom <= top:
            logger.warning(f"  ✗ Graph {idx}: degenerate crop box, skipping")
            continue

        crop = img.crop((left, top, right, bottom))
        out_path = output_dir / f"{idx:03d}_graph_{idx - 1}.png"
        crop.save(str(out_path))
        size_kb = out_path.stat().st_size // 1024
        logger.info(f"  ✓ Graph {idx}: ({right-left}×{bottom-top}px) → {out_path.name} ({size_kb}KB)")
        crops.append(out_path)

    return crops


def _crop_strip_sections(
    full_page_path: Path,
    output_dir: Path,
    viewport_height: int,
    overlap: float = 0.2,
) -> list[Path]:
    """
    Fallback: slice the full-page PNG into viewport-height strips with overlap.
    Named graph_*.png for consistency with the primary path.
    """
    img = Image.open(full_page_path)
    img_w, img_h = img.size
    step = max(1, int(viewport_height * (1 - overlap)))

    crops: list[Path] = []
    position = 0
    idx = 1

    while position < img_h:
        bottom = min(img_h, position + viewport_height)
        strip = img.crop((0, position, img_w, bottom))
        out_path = output_dir / f"{idx:03d}_graph_{idx - 1}.png"
        strip.save(str(out_path))
        size_kb = out_path.stat().st_size // 1024
        logger.info(f"  ✓ Strip {idx}: y={position}–{bottom} → {out_path.name} ({size_kb}KB)")
        crops.append(out_path)
        position += step
        idx += 1

    return crops


async def capture_cloudhealth_screenshots(
    config_path: Path,
    temp_dir: Path,
    cdp_port: int = 9222
) -> tuple[list[Path], dict]:
    """
    Main screenshot capture function for CloudHealth dashboard.
    
    Args:
        config_path: Path to dashboards.yaml config
        temp_dir: Temporary directory for screenshots
        cdp_port: CDP port for browser connection
    
    Returns:
        Tuple of (screenshot_paths, dashboard_info_dict)
    
    Raises:
        BrowserConnectionError: If can't connect to browser
        ScreenshotCaptureError: If screenshot capture fails
    """
    logger.info("Starting CloudHealth screenshot capture...")
    
    # Create temp directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_dir = temp_dir / f"screenshots_{timestamp}"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Screenshot directory: {screenshot_dir}")
    
    pw = await async_playwright().start()
    screenshots = []
    dashboard_info = {}
    
    try:
        # Connect to browser
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
            context = browser.contexts[0]
        except Exception as e:
            raise BrowserConnectionError(f"Failed to connect to browser: {e}")
        
        # Get CloudHealth URL from config
        config = yaml.safe_load(config_path.read_text())
        cloudhealth_url = None
        for db in config.get("dashboards", []):
            if db.get("auth_type") == "cloudhealth":
                cloudhealth_url = db.get("url")
                break
        
        if not cloudhealth_url:
            raise ScreenshotCaptureError("CloudHealth URL not found in dashboards.yaml")
        
        # Find or create CloudHealth tab
        page = None
        for p in context.pages:
            if "cloudhealthtech.com" in p.url:
                page = p
                break
        
        if not page:
            logger.info("Opening new CloudHealth tab...")
            page = await context.new_page()
            await page.goto(cloudhealth_url)
        else:
            logger.info("Using existing CloudHealth tab...")
            await page.bring_to_front()
        
        # Wait for dashboard to load
        logger.info("Waiting for dashboard to load...")
        await page.wait_for_load_state("load")
        await asyncio.sleep(4)  # Give charts time to render

        # Try to wait for chart elements
        try:
            await page.wait_for_selector(
                '[class*="chart"], [class*="widget"], canvas, [class*="graph"]',
                timeout=8000
            )
            logger.info("✓ Dashboard charts detected")
        except Exception:
            logger.warning("⚠ No chart selectors found, continuing anyway...")
        
        # Collect dashboard info
        title = await page.title()
        url = page.url
        
        dashboard_info = {
            "title": title,
            "url": url,
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot_dir": str(screenshot_dir),
        }
        
        logger.info(f"Dashboard: {title}")
        logger.info(f"URL: {url}")
        
        # Capture full page
        screenshots = await capture_full_page(page, screenshot_dir)
        
        logger.info(f"✓ Captured {len(screenshots)} screenshots total")
        
        # Don't close the browser
        browser.close = lambda: asyncio.sleep(0)
        
    except BrowserConnectionError:
        raise
    except ScreenshotCaptureError:
        raise
    except Exception as e:
        raise ScreenshotCaptureError(f"Unexpected error during screenshot capture: {e}")
    finally:
        await pw.stop()
    
    return screenshots, dashboard_info
