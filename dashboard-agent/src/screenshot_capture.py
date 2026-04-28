"""Screenshot Capture Module

Handles connection to browser and systematic screenshot capture of dashboard pages.
Captures entire page content and crops visible graphs into individual images.
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


async def capture_graphs_from_url(
    name: str,
    url: str,
    output_dir: Path,
    cdp_port: int = 9222,
) -> tuple[list[Path], dict]:
    """
    Capture individual graph images from a URL using the generic screenshot utility.

    Args:
        name: Caller-provided display name for the URL source
        url: Dashboard/page URL to capture
        output_dir: Directory where screenshots and graph crops should be written
        cdp_port: Chrome DevTools Protocol port for the existing browser session

    Returns:
        Tuple of (graph_paths, page_info_dict). graph_paths excludes the
        full-page overview when individual crops/strips were produced.

    Raises:
        BrowserConnectionError: If can't connect to browser
        ScreenshotCaptureError: If screenshot capture fails
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Starting graph capture for {name}: {url}")
    logger.info(f"Screenshot directory: {output_dir}")

    pw = await async_playwright().start()
    screenshots: list[Path] = []
    page_info: dict = {}

    try:
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
            context = browser.contexts[0]
        except Exception as e:
            raise BrowserConnectionError(f"Failed to connect to browser: {e}") from e

        page = None
        for existing_page in context.pages:
            if existing_page.url == url:
                page = existing_page
                break

        if page:
            logger.info(f"Using existing tab for {name}...")
            await page.bring_to_front()
        else:
            logger.info(f"Opening new tab for {name}...")
            page = await context.new_page()
            await page.goto(url)

        logger.info("Waiting for page to load...")
        await page.wait_for_load_state("load")
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            logger.info("Network did not go idle before timeout; continuing...")
        await asyncio.sleep(4)

        try:
            await page.wait_for_selector(
                'svg, canvas, [class*="chart"], [class*="widget"], [class*="graph"]',
                timeout=8000,
            )
            logger.info("✓ Graph-like elements detected")
        except Exception:
            logger.warning("No graph selectors found, continuing with full-page crop fallback...")

        title = await page.title()
        page_info = {
            "title": title or name,
            "url": page.url,
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot_dir": str(output_dir),
        }

        screenshots = await capture_full_page(page, output_dir)
        graph_paths = [path for path in screenshots if path.name != "000_full_page.png"]
        if not graph_paths:
            graph_paths = screenshots

        logger.info(f"✓ Captured {len(graph_paths)} graph images from {name}")

        # Don't close the browser
        browser.close = lambda: asyncio.sleep(0)
        return graph_paths, page_info

    except BrowserConnectionError:
        raise
    except ScreenshotCaptureError:
        raise
    except Exception as e:
        raise ScreenshotCaptureError(f"Unexpected error during URL graph capture: {e}") from e
    finally:
        await pw.stop()


async def capture_full_page(
    page: Page,
    output_dir: Path,
) -> list[Path]:
    """
    Capture the entire page content including inside scrollable containers (SPAs).

    Strategy:
      1. Find the primary document or SPA scroll container.
      2. Scroll through it once so lazy-loaded charts render.
      3. Expand SPA scroll containers when needed.
      4. Take a true full-page screenshot at CSS-pixel scale.
      5. Crop one image per detected graph/card boundary.
    """
    screenshots = []

    container_info = await _mark_scroll_container(page)
    scroll_height = container_info.get("scrollHeight", 0)
    client_height = container_info.get("clientHeight", 0)
    use_document = container_info.get("useDocument", True)
    selector = container_info.get("selector")

    logger.info(f"Scroll container: {'document' if use_document else selector}")
    logger.info(f"Content height: {scroll_height}px  |  Visible height: {client_height}px")

    original_vp = page.viewport_size or {"width": 1920, "height": 1080}
    prepared_frames: list[dict] = []

    try:
        await _prime_lazy_content(page, use_document)
        capture_info = await _expand_scroll_container_for_capture(page, use_document)
        prepared_frames = await _prepare_embedded_frames_for_capture(page)
        await asyncio.sleep(2)  # Give charts time to re-render after expansion

        full_page_path = output_dir / "000_full_page.png"
        try:
            await page.screenshot(
                path=str(full_page_path),
                full_page=True,
                scale="css",
            )
        except Exception as e:
            raise ScreenshotCaptureError(f"Failed to capture full-page screenshot: {e}") from e
        screenshots.append(full_page_path)
        size_kb = full_page_path.stat().st_size // 1024
        logger.info(
            f"  ✓ Full-page screenshot: {full_page_path.name} "
            f"({size_kb}KB, height={capture_info.get('captureHeight', scroll_height)}px)"
        )

        # Collect chart bounding boxes while the page is still expanded. The
        # screenshot is taken at CSS scale, so these CSS-pixel coordinates match.
        boxes = [] if prepared_frames else await _collect_chart_boxes(page)
        for prepared in prepared_frames:
            frame_boxes = await _collect_chart_boxes(prepared["frame"])
            offset = await _frame_page_offset(prepared["frame"])
            boxes.extend(
                {
                    "x": box["x"] + offset["x"],
                    "y": box["y"] + offset["y"],
                    "width": box["width"],
                    "height": box["height"],
                }
                for box in frame_boxes
            )

    finally:
        for prepared in prepared_frames:
            await _restore_scroll_container(prepared["frame"])
        await _restore_frame_elements(page)
        await _restore_scroll_container(page)
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


async def _mark_scroll_container(page: Page) -> dict:
    """Find and mark the page's primary scroll container for capture."""
    return await page.evaluate("""() => {
        document
            .querySelectorAll('[data-dashboard-agent-scroll-root="true"]')
            .forEach(el => el.removeAttribute('data-dashboard-agent-scroll-root'));

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
        el.setAttribute('data-dashboard-agent-scroll-root', 'true');
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


async def _prime_lazy_content(page: Page, use_document: bool) -> None:
    """Scroll through the page once so lazy-loaded charts render before capture."""
    await page.evaluate("""async (useDocument) => {
        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
        const root = useDocument
            ? (document.scrollingElement || document.documentElement)
            : document.querySelector('[data-dashboard-agent-scroll-root="true"]');
        if (!root) return;

        const viewportHeight = useDocument ? window.innerHeight : root.clientHeight;
        const maxScroll = Math.max(0, root.scrollHeight - viewportHeight);
        const step = Math.max(400, Math.floor(viewportHeight * 0.75));

        for (let y = 0; y <= maxScroll; y += step) {
            if (useDocument) window.scrollTo(0, y);
            else root.scrollTop = y;
            await sleep(250);
        }
        if (useDocument) window.scrollTo(0, 0);
        else root.scrollTop = 0;
        await sleep(500);
    }""", use_document)


async def _expand_scroll_container_for_capture(page: Page, use_document: bool) -> dict:
    """Expand SPA scroll containers so full_page screenshots include all content."""
    if use_document:
        return await page.evaluate("""() => ({
            captureHeight: Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight
            )
        })""")

    return await page.evaluate("""() => {
        const root = document.querySelector('[data-dashboard-agent-scroll-root="true"]');
        if (!root) {
            return {
                captureHeight: Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight
                )
            };
        }

        const touched = [];
        const remember = el => {
            touched.push([el, el.getAttribute('style')]);
        };

        let el = root;
        while (el && el.nodeType === Node.ELEMENT_NODE) {
            remember(el);
            if (el === root) {
                el.style.height = root.scrollHeight + 'px';
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
                el.style.overflowY = 'visible';
            } else {
                const style = window.getComputedStyle(el);
                if (/(auto|scroll|hidden|clip)/.test(style.overflow + ' ' + style.overflowY)) {
                    el.style.overflow = 'visible';
                    el.style.overflowY = 'visible';
                }
                el.style.maxHeight = 'none';
            }
            if (el === document.body || el === document.documentElement) break;
            el = el.parentElement;
        }

        window.__dashboardAgentScrollRestore = touched;
        return {
            captureHeight: Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight,
                root.scrollHeight
            )
        };
    }""")


async def _restore_scroll_container(page: Page) -> None:
    """Restore inline styles changed for full-page capture."""
    try:
        await page.evaluate("""() => {
            const touched = window.__dashboardAgentScrollRestore || [];
            for (let i = touched.length - 1; i >= 0; i--) {
                const [el, style] = touched[i];
                if (!el) continue;
                if (style === null) el.removeAttribute('style');
                else el.setAttribute('style', style);
            }
            delete window.__dashboardAgentScrollRestore;
            document
                .querySelectorAll('[data-dashboard-agent-scroll-root="true"]')
                .forEach(el => el.removeAttribute('data-dashboard-agent-scroll-root'));
        }""")
    except Exception as e:
        logger.warning(f"Failed to restore scroll container styles: {e}")


async def _prepare_embedded_frames_for_capture(page: Page) -> list[dict]:
    """Expand embedded dashboard frames so their internal scroll content is visible."""
    prepared: list[dict] = []
    for frame in page.frames:
        if frame == page.main_frame:
            continue

        try:
            frame_info = await _mark_scroll_container(frame)
            frame_scroll_height = frame_info.get("scrollHeight", 0)
            frame_client_height = frame_info.get("clientHeight", 0)
            if frame_scroll_height <= frame_client_height + 20:
                continue

            await _prime_lazy_content(frame, frame_info.get("useDocument", True))
            capture_info = await _expand_scroll_container_for_capture(
                frame,
                frame_info.get("useDocument", True),
            )
            capture_height = max(
                int(capture_info.get("captureHeight", 0) or 0),
                int(frame_scroll_height or 0),
                int(frame_client_height or 0),
            )
            await _expand_frame_element_for_capture(frame, capture_height)
            prepared.append({"frame": frame})
            logger.info(
                f"  Expanded embedded frame for capture: "
                f"{frame_client_height}px -> {capture_height}px"
            )
        except Exception as e:
            logger.warning(f"Could not prepare embedded frame for capture: {e}")

    return prepared


async def _expand_frame_element_for_capture(frame, capture_height: int) -> None:
    """Expand an iframe element and ancestors in the parent page."""
    frame_element = await frame.frame_element()
    await frame_element.evaluate("""(iframe, captureHeight) => {
        const touched = window.__dashboardAgentFrameRestore || [];
        const remember = el => {
            if (!touched.some(([existing]) => existing === el)) {
                touched.push([el, el.getAttribute('style')]);
            }
        };

        const iframeTop = iframe.getBoundingClientRect().top + window.scrollY;
        for (let el = iframe; el && el.nodeType === Node.ELEMENT_NODE; el = el.parentElement) {
            remember(el);

            const rect = el.getBoundingClientRect();
            const elTop = rect.top + window.scrollY;
            const neededHeight = Math.ceil(iframeTop - elTop + captureHeight);

            el.style.maxHeight = 'none';
            el.style.overflow = 'visible';
            el.style.overflowY = 'visible';

            if (el === iframe) {
                el.style.height = captureHeight + 'px';
                el.style.minHeight = captureHeight + 'px';
            } else if (neededHeight > rect.height) {
                el.style.minHeight = neededHeight + 'px';
            }

            if (el === document.body || el === document.documentElement) break;
        }

        window.__dashboardAgentFrameRestore = touched;
    }""", capture_height)


async def _restore_frame_elements(page: Page) -> None:
    """Restore iframe/ancestor styles changed for embedded-frame capture."""
    try:
        await page.evaluate("""() => {
            const touched = window.__dashboardAgentFrameRestore || [];
            for (let i = touched.length - 1; i >= 0; i--) {
                const [el, style] = touched[i];
                if (!el) continue;
                if (style === null) el.removeAttribute('style');
                else el.setAttribute('style', style);
            }
            delete window.__dashboardAgentFrameRestore;
        }""")
    except Exception as e:
        logger.warning(f"Failed to restore embedded frame styles: {e}")


async def _frame_page_offset(frame) -> dict:
    """Return the iframe's top-left coordinate in the outer page screenshot."""
    frame_element = await frame.frame_element()
    return await frame_element.evaluate("""iframe => {
        const r = iframe.getBoundingClientRect();
        return {
            x: r.left + window.scrollX,
            y: r.top + window.scrollY
        };
    }""")


async def _collect_chart_boxes(page: Page) -> list[dict]:
    """
    Return de-duplicated bounding boxes of chart elements in document coordinates.

    Uses SVG/canvas element detection and then climbs to the nearest single-chart
    card/container so crops include titles and legends without swallowing adjacent
    dashboard cards.

    Strategy:
    - Find large SVG/canvas chart roots.
    - For each root, walk up ancestors while the candidate still contains only
      that one large chart root.
    - Prefer card-like wrappers and reject page-level containers.
    - De-duplicate near-identical boxes using intersection-over-union.
    """
    boxes: list[dict] = await page.evaluate("""
        () => {
            const MIN_W = 180;
            const MIN_H = 120;
            const viewportW = window.innerWidth || 1920;
            const viewportH = window.innerHeight || 1080;

            function rectOf(el) {
                const r = el.getBoundingClientRect();
                return {
                    left: r.left,
                    top: r.top,
                    width: r.width,
                    height: r.height,
                    right: r.right,
                    bottom: r.bottom
                };
            }

            function isVisibleRect(r) {
                return r.width >= MIN_W && r.height >= MIN_H;
            }

            function isLargeChartRoot(el) {
                const tag = el.tagName.toLowerCase();
                if (tag !== 'svg' && tag !== 'canvas') return false;
                const r = rectOf(el);
                if (!isVisibleRect(r)) return false;
                if (tag === 'svg' && el.parentElement && el.parentElement.closest('svg')) {
                    return false;
                }
                return true;
            }

            function largeChartRootsWithin(el) {
                const roots = [];
                if (isLargeChartRoot(el)) roots.push(el);
                for (const child of el.querySelectorAll('svg, canvas')) {
                    if (isLargeChartRoot(child)) roots.push(child);
                }
                return roots;
            }

            function containsOnlyRoot(el, root) {
                const roots = largeChartRootsWithin(el);
                return roots.length === 1 && roots[0] === root;
            }

            function classText(el) {
                const cls = typeof el.className === 'string'
                    ? el.className
                    : (el.className && el.className.baseVal) || '';
                return [
                    cls,
                    el.id || '',
                    el.getAttribute('role') || '',
                    el.getAttribute('data-testid') || '',
                    el.getAttribute('aria-label') || ''
                ].join(' ');
            }

            function isCardLike(el) {
                return /(card|panel|paper|widget|tile|chart|graph|visual|dashboard-item|react-grid-item|grid-item|highcharts-container|recharts-wrapper|plotly|echarts|MuiPaper|chakra-card)/i
                    .test(classText(el));
            }

            function tooPageLike(r, rootRect) {
                if (r.width >= viewportW * 0.98 && r.height >= viewportH * 0.80) return true;
                if (r.height > Math.max(rootRect.height * 3.5, rootRect.height + 520)) return true;
                if (r.width > Math.max(rootRect.width * 3.0, rootRect.width + 720)) return true;
                return false;
            }

            function boxFromRect(r) {
                return {
                    x: Math.max(0, r.left + window.scrollX),
                    y: Math.max(0, r.top + window.scrollY),
                    width: r.width,
                    height: r.height
                };
            }

            function chooseGraphContainer(root) {
                const rootRect = rectOf(root);
                let best = root;
                let bestScore = 0;

                for (let el = root; el && el.tagName !== 'BODY' && el.tagName !== 'HTML'; el = el.parentElement) {
                    if (!containsOnlyRoot(el, root)) break;
                    const r = rectOf(el);
                    if (r.width < rootRect.width - 5 || r.height < rootRect.height - 5) continue;
                    if (tooPageLike(r, rootRect)) break;

                    const extraW = r.width - rootRect.width;
                    const extraH = r.height - rootRect.height;
                    const hasUsefulWrapperSpace = extraW <= 520 && extraH <= 360;
                    const cardLike = isCardLike(el);
                    if (!cardLike && !hasUsefulWrapperSpace) continue;

                    const score =
                        (cardLike ? 1000 : 0) +
                        Math.min(400, Math.max(0, extraW)) +
                        Math.min(400, Math.max(0, extraH)) +
                        (el.getAttribute('role') === 'figure' ? 250 : 0);

                    if (score >= bestScore) {
                        best = el;
                        bestScore = score;
                    }
                }

                return boxFromRect(rectOf(best));
            }

            function isTooLargeForCard(r) {
                return r.width >= viewportW * 0.98 && r.height >= viewportH * 0.92;
            }

            function isDashboardTileSeed(el) {
                const r = rectOf(el);
                if (r.width < 260 || r.height < 120 || isTooLargeForCard(r)) return false;

                const signal = classText(el);
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (el.id === 'styled-tile-dashboard') return true;
                if (/react-grid-item|Element__ElementCard|dashboard-tile|tile|vis-container/i.test(signal)) return true;
                if (/No Results/i.test(el.getAttribute('aria-label') || '')) return true;
                if (/No results/i.test(text) && r.width > 300 && r.height > 200) return true;
                return false;
            }

            function chooseDashboardTile(seed) {
                let best = seed;
                for (let el = seed; el && el.tagName !== 'BODY' && el.tagName !== 'HTML'; el = el.parentElement) {
                    const r = rectOf(el);
                    if (r.width < 260 || r.height < 160 || isTooLargeForCard(r)) continue;

                    const signal = classText(el);
                    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                    const looksLikeTile =
                        el.id === 'styled-tile-dashboard' ||
                        /react-grid-item|Element__ElementCard/i.test(signal) ||
                        (/Card/i.test(signal) && (/Chart|No results|Tile actions/i.test(text)));

                    if (looksLikeTile) {
                        best = el;
                        if (el.id === 'styled-tile-dashboard' || /react-grid-item/i.test(signal)) {
                            break;
                        }
                    }
                }
                return boxFromRect(rectOf(best));
            }

            const dashboardCards = [...document.querySelectorAll('*')]
                .filter(isDashboardTileSeed)
                .map(chooseDashboardTile)
                .filter(b => b.width >= 260 && b.height >= 160);

            const roots = [...document.querySelectorAll('svg, canvas')]
                .filter(isLargeChartRoot);

            const candidates = [
                ...dashboardCards,
                ...roots.map(chooseGraphContainer),
            ].filter(b => b.width >= MIN_W && b.height >= MIN_H);

            function area(b) {
                return b.width * b.height;
            }

            function iou(a, b) {
                const left = Math.max(a.x, b.x);
                const top = Math.max(a.y, b.y);
                const right = Math.min(a.x + a.width, b.x + b.width);
                const bottom = Math.min(a.y + a.height, b.y + b.height);
                const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
                if (!intersection) return 0;
                return intersection / (area(a) + area(b) - intersection);
            }

            candidates.sort((a, b) => area(b) - area(a));
            const deduped = [];
            for (const candidate of candidates) {
                if (deduped.some(existing => iou(existing, candidate) > 0.82)) continue;
                deduped.push(candidate);
            }

            function contains(outer, inner) {
                return outer.x <= inner.x + 12 &&
                    outer.y <= inner.y + 12 &&
                    outer.x + outer.width >= inner.x + inner.width - 12 &&
                    outer.y + outer.height >= inner.y + inner.height - 12;
            }

            const graphBoxes = deduped.filter(candidate =>
                deduped.filter(other => other !== candidate && contains(candidate, other)).length < 2
            );

            return graphBoxes.sort((a, b) => (a.y - b.y) || (a.x - b.x));
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
