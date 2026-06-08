"""Screenshot Capture Module

Handles connection to browser and systematic screenshot capture of dashboard pages.
Captures entire page content and crops visible graphs into individual images.
"""
import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
from PIL import Image
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, Page
import yaml

logger = logging.getLogger(__name__)


class ScreenshotCaptureError(Exception):
    """Raised when screenshot capture fails."""
    pass


class BrowserConnectionError(Exception):
    """Raised when unable to connect to browser."""
    pass


_LOGIN_DOMAINS = (
    "login.microsoftonline.com",
    "device.login.microsoftonline.com",
    "auth.cloudzero.com",
    "login.tableau.com",
    "sso.online.tableau.com",
)
_VOLATILE_QUERY_KEYS = {"iid", "session", "authuser", "prompt"}
CAPTURE_NAVIGATION_TIMEOUT_MS = 60_000
CAPTURE_LOAD_STATE_TIMEOUT_MS = 10_000


def _is_login_redirect(url: str) -> bool:
    return any(domain in url for domain in _LOGIN_DOMAINS)


def _normalized_query_items(query: str) -> frozenset[tuple[str, str]]:
    query = query.lstrip("?")
    items = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.lower().lstrip(":")
        if normalized_key in _VOLATILE_QUERY_KEYS:
            continue
        items.append((normalized_key, value))
    return frozenset(items)


def _url_signature(url: str) -> dict:
    parsed = urlparse(url)
    fragment_path, _, fragment_query = parsed.fragment.partition("?")
    return {
        "host": parsed.netloc.lower(),
        "path": (parsed.path or "/").rstrip("/") or "/",
        "fragment_path": fragment_path.rstrip("/"),
        "query": _normalized_query_items(parsed.query),
        "fragment_query": _normalized_query_items(fragment_query),
    }


def _url_match_score(requested_url: str, candidate_url: str) -> int:
    """Score how likely an existing browser tab is the requested dashboard URL."""
    if not candidate_url or _is_login_redirect(candidate_url):
        return 0
    if requested_url == candidate_url:
        return 10_000

    requested = _url_signature(requested_url)
    candidate = _url_signature(candidate_url)
    if requested["host"] != candidate["host"]:
        return 0
    if requested["path"] != candidate["path"]:
        return 0
    if requested["fragment_path"] and candidate["fragment_path"]:
        if requested["fragment_path"] != candidate["fragment_path"]:
            return 0
    elif requested["fragment_path"] != candidate["fragment_path"]:
        return 0

    score = 1_000
    for key in ("query", "fragment_query"):
        requested_items = requested[key]
        candidate_items = candidate[key]
        if requested_items:
            if not requested_items.issubset(candidate_items):
                return 0
            score += 10 * len(requested_items)
        elif candidate_items:
            score += 1
    return score


def _find_existing_page_for_url(pages, url: str):
    scored_pages = [
        (_url_match_score(url, getattr(page, "url", "")), page)
        for page in pages
    ]
    scored_pages = [(score, page) for score, page in scored_pages if score > 0]
    if not scored_pages:
        return None
    return max(scored_pages, key=lambda item: item[0])[1]


def _is_dashboard_view_url(url: str) -> bool:
    """Return true for dashboard collection views such as CloudZero /view pages."""
    parsed = urlparse(url)
    return parsed.path.rstrip("/").endswith("/view")


async def _goto_for_capture(page: Page, url: str) -> None:
    """Navigate for capture without requiring SPA pages to fire the full load event."""
    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=CAPTURE_NAVIGATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        current_url = getattr(page, "url", "")
        if current_url and not _is_login_redirect(current_url):
            logger.warning(
                "Navigation timed out before DOMContentLoaded; continuing from current URL: %s",
                current_url,
            )
            return
        raise


async def _wait_for_initial_load(page: Page) -> None:
    """Wait briefly for load states, but let readiness detection decide final capture timing."""
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=CAPTURE_LOAD_STATE_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        logger.info("DOM content did not report ready before timeout; continuing...")

    try:
        await page.wait_for_load_state(
            "load",
            timeout=CAPTURE_LOAD_STATE_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        logger.info("Load event did not complete before timeout; continuing...")


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
    page: Page | None = None
    opened_page = False

    try:
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
            context = browser.contexts[0]
        except Exception as e:
            raise BrowserConnectionError(f"Failed to connect to browser: {e}") from e

        page = _find_existing_page_for_url(context.pages, url)

        if page:
            logger.info(f"Using existing tab for {name}...")
            await page.bring_to_front()
        else:
            logger.info(f"Opening new tab for {name}...")
            page = await context.new_page()
            opened_page = True
            await _goto_for_capture(page, url)

        logger.info("Waiting for page to load...")
        await _wait_for_initial_load(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            logger.info("Network did not go idle before timeout; continuing...")
        dashboard_view = _is_dashboard_view_url(page.url) or _is_dashboard_view_url(url)
        await _wait_for_capture_ready(page, dashboard_view=dashboard_view)

        title = await page.title()
        page_info = {
            "title": title or name,
            "url": page.url,
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "screenshot_dir": str(output_dir),
        }

        screenshots = await capture_full_page(
            page,
            output_dir,
            dashboard_view=dashboard_view,
        )
        graph_paths = [path for path in screenshots if path.name != "000_full_page.png"]
        if not graph_paths:
            raise ScreenshotCaptureError(f"No reliable graph crops found for {name}")

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
        if opened_page and page is not None:
            try:
                await page.close()
            except Exception as e:
                logger.debug(f"Could not close temporary capture tab for {name}: {e}")
        await pw.stop()


async def capture_full_page(
    page: Page,
    output_dir: Path,
    dashboard_view: bool = False,
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
        css_size = await _capture_css_size(page, capture_info)

        # Collect chart bounding boxes while the page is still expanded. The
        # boxes are CSS-pixel document coordinates. The screenshot may still be
        # device-pixel sized in a persistent browser, so crop scaling happens
        # after the PNG is loaded.
        boxes = await _collect_capture_boxes(
            page,
            dashboard_view,
            warn_on_fallback=not prepared_frames,
        )
        for prepared in prepared_frames:
            frame_boxes = await _collect_capture_boxes(prepared["frame"], dashboard_view)
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
        crops = _crop_graphs_from_full_page(full_page_path, boxes, output_dir, css_size=css_size)
        screenshots.extend(crops)
        logger.info(f"  ✓ Cropped {len(crops)} graphs from full-page image")
    else:
        logger.warning("  No reliable chart elements detected; skipping graph crops")

    return screenshots


async def _wait_for_capture_ready(
    page: Page,
    dashboard_view: bool = False,
    timeout_ms: int = 45_000,
    poll_ms: int = 1_000,
) -> list[dict]:
    """
    Wait until the page has stable chart/no-results candidates before capture.

    SPA dashboards often fire the load event before charts finish rendering. This
    gate waits for useful candidates with stable dimensions and avoids treating
    filters or loading shells as graph crops.
    """
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    previous_signature = None
    stable_ticks = 0
    previous_table_signature = None
    table_stable_ticks = 0
    last_boxes: list[dict] = []
    last_table_boxes: list[dict] = []
    last_loading_count = 0

    while asyncio.get_running_loop().time() < deadline:
        if _is_login_redirect(page.url):
            raise ScreenshotCaptureError(f"Page redirected to login before capture: {page.url}")

        last_loading_count = await _visible_loading_indicator_count(page)
        last_boxes = await _collect_ready_boxes(page, dashboard_view)
        last_table_boxes = await _collect_ready_table_boxes(page, dashboard_view)
        signature = _box_signature(last_boxes)
        table_signature = _box_signature(last_table_boxes)

        if last_boxes and signature == previous_signature:
            stable_ticks += 1
        else:
            stable_ticks = 0
            previous_signature = signature

        if not last_boxes and last_table_boxes and table_signature == previous_table_signature:
            table_stable_ticks += 1
        else:
            table_stable_ticks = 0
            previous_table_signature = table_signature

        if last_boxes and stable_ticks >= 2 and last_loading_count == 0:
            logger.info(f"✓ Capture-ready charts detected ({len(last_boxes)} stable candidate(s))")
            return last_boxes

        if (
            not last_boxes
            and last_table_boxes
            and table_stable_ticks >= 2
            and last_loading_count == 0
        ):
            raise ScreenshotCaptureError(
                "Stable data table detected but no graph candidates were found"
            )

        await asyncio.sleep(poll_ms / 1000)

    if last_boxes and stable_ticks >= 1:
        logger.warning(
            "Capture readiness timed out with %s loading indicator(s); using %s stable candidate(s)",
            last_loading_count,
            len(last_boxes),
        )
        return last_boxes

    if last_table_boxes and table_stable_ticks >= 1:
        raise ScreenshotCaptureError(
            "Stable data table detected but no graph candidates were found"
        )

    raise ScreenshotCaptureError("No stable chart or no-results candidates were found before timeout")


async def _collect_ready_boxes(page: Page, dashboard_view: bool) -> list[dict]:
    """Collect capture candidates from the main page and embedded frames for readiness checks."""
    boxes = await _collect_capture_boxes(page, dashboard_view, warn_on_fallback=False)
    for frame in page.frames:
        if frame is page.main_frame:
            continue
        try:
            boxes.extend(await _collect_capture_boxes(frame, dashboard_view, warn_on_fallback=False))
        except Exception as e:
            logger.debug(f"Could not collect readiness boxes from frame {frame.url}: {e}")
    return boxes


async def _collect_ready_table_boxes(page: Page, dashboard_view: bool) -> list[dict]:
    """Collect standalone table candidates used to fail fast for non-graph pages."""
    boxes = []
    if not dashboard_view:
        boxes = await _collect_standalone_table_boxes(page)
    for frame in page.frames:
        if frame is page.main_frame:
            continue
        try:
            boxes.extend(await _collect_standalone_table_boxes(frame))
        except Exception as e:
            logger.debug(f"Could not collect readiness table boxes from frame {frame.url}: {e}")
    return boxes


async def _capture_css_size(page: Page, capture_info: dict) -> dict:
    try:
        size = await page.evaluate("""() => ({
            width: Math.max(
                document.body.scrollWidth,
                document.documentElement.scrollWidth,
                window.innerWidth
            ),
            height: Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight,
                window.innerHeight
            )
        })""")
    except Exception:
        size = {}

    return {
        "width": int(size.get("width") or 0),
        "height": int(size.get("height") or capture_info.get("captureHeight") or 0),
    }


def _box_signature(boxes: list[dict]) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        sorted(
            (
                round(float(box.get("x", 0))),
                round(float(box.get("y", 0))),
                round(float(box.get("width", 0))),
                round(float(box.get("height", 0))),
            )
            for box in boxes
        )
    )


async def _visible_loading_indicator_count(page: Page) -> int:
    try:
        return await page.evaluate("""
            () => {
                const selectors = [
                    '[aria-busy="true"]',
                    '[role="progressbar"]',
                    '[class*="loading" i]',
                    '[class*="spinner" i]',
                    '[class*="skeleton" i]',
                    '[class*="progress" i]',
                    '[data-testid*="loading" i]',
                    '[data-testid*="skeleton" i]'
                ];

                function visible(el) {
                    const style = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && r.width > 8
                        && r.height > 8;
                }

                const found = new Set();
                for (const selector of selectors) {
                    for (const el of document.querySelectorAll(selector)) {
                        if (visible(el)) found.add(el);
                    }
                }

                for (const el of document.querySelectorAll('body *')) {
                    const text = (el.innerText || '').trim();
                    if (/^(loading|loading\\.\\.\\.|please wait)$/i.test(text) && visible(el)) {
                        found.add(el);
                    }
                }
                return found.size;
            }
        """)
    except Exception as e:
        logger.debug(f"Could not evaluate loading indicators: {e}")
        return 0


async def _mark_scroll_container(page: Page) -> dict:
    """Find and mark the page's primary scroll container for capture."""
    return await page.evaluate("""() => {
        document
            .querySelectorAll('[data-dashboard-agent-scroll-root="true"]')
            .forEach(el => el.removeAttribute('data-dashboard-agent-scroll-root'));

        // First check for CloudZero next.cloudzero.com structure: main[data-scroll-container="main"]
        const cloudZeroMain = document.querySelector('main[data-scroll-container="main"]');
        if (cloudZeroMain) {
            const rect = cloudZeroMain.getBoundingClientRect();
            if (cloudZeroMain.scrollHeight > cloudZeroMain.clientHeight + 50 && rect.height > 200 && rect.width > 200) {
                cloudZeroMain.setAttribute('data-dashboard-agent-scroll-root', 'true');
                return {
                    useDocument: false,
                    scrollHeight: cloudZeroMain.scrollHeight,
                    clientHeight: cloudZeroMain.clientHeight,
                    selector: 'main[data-scroll-container="main"]'
                };
            }
        }

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


async def _collect_capture_boxes(
    page: Page,
    dashboard_view: bool,
    warn_on_fallback: bool = True,
) -> list[dict]:
    if dashboard_view:
        boxes = await _collect_dashboard_tile_boxes(page)
        if boxes:
            return boxes
        if warn_on_fallback:
            logger.warning("  Dashboard view tile detector found no tiles; trying chart detector")
    return await _collect_chart_boxes(page)


async def _collect_standalone_table_boxes(page: Page) -> list[dict]:
    """Return table-like content boxes used to identify non-graph detail pages."""
    snapshot: dict = await page.evaluate("""
        () => {
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

            function classText(el) {
                const cls = typeof el.className === 'string'
                    ? el.className
                    : (el.className && el.className.baseVal) || '';
                return [
                    cls,
                    el.id || '',
                    el.getAttribute('role') || '',
                    el.getAttribute('data-testid') || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('data-test') || ''
                ].join(' ');
            }

            function visible(el, r) {
                const style = window.getComputedStyle(el);
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && r.width >= 320
                    && r.height >= 140;
            }

            function rowCount(el) {
                return el.querySelectorAll(
                    'tr, [role="row"], .tab-row, .tab-vizRow, .ag-row, [class*="row" i]'
                ).length;
            }

            function cellCount(el) {
                return el.querySelectorAll(
                    'td, th, [role="cell"], [role="gridcell"], .tab-cell, .tab-vizCell, .ag-cell, [class*="cell" i]'
                ).length;
            }

            function tableLike(el) {
                const signal = classText(el);
                return el.tagName === 'TABLE'
                    || ['table', 'grid', 'rowgroup'].includes(el.getAttribute('role') || '')
                    || el.getAttribute('data-testid') === 'table-root'
                    || /\\b(table|grid|data-grid|ag-grid|tab-tv|tab-viz|tabular|datatable|dataTable|worksheet)\\b/i.test(signal);
            }

            function usefulTableText(el) {
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                return /(CVE|Vulnerab|Severity|Finding|Tanium|Asset|Host|Account|Package|Title|Status|Owner|Due Date|Total|Count|Risk|Remediation)/i.test(text);
            }

            const raw = [...document.querySelectorAll(
                'table, [role="table"], [role="grid"], [role="rowgroup"], [data-testid="table-root"], ' +
                '.ag-center-cols-container, [class*="table" i], [class*="grid" i], [class*="tab-tv" i], [class*="tab-viz" i], [class*="datatable" i]'
            )];

            const candidates = raw
                .map(el => ({
                    el,
                    r: rectOf(el),
                    rows: rowCount(el),
                    cells: cellCount(el),
                    text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 360),
                    signal: classText(el),
                    hasChart: !!el.querySelector('svg, canvas, .ag-charts-canvas-container')
                }))
                .filter(item => visible(item.el, item.r))
                .filter(item => !item.hasChart)
                .filter(item => tableLike(item.el) || item.rows >= 4 || item.cells >= 8)
                .filter(item => item.rows >= 3 || item.cells >= 8 || usefulTableText(item.el))
                .map(item => ({
                    x: Math.max(0, item.r.left + window.scrollX),
                    y: Math.max(0, item.r.top + window.scrollY),
                    width: item.r.width,
                    height: item.r.height,
                    rows: item.rows,
                    cells: item.cells,
                    text: item.text,
                    signal: item.signal,
                    tableOnly: true
                }));

            return {
                viewportWidth: viewportW,
                viewportHeight: viewportH,
                candidates
            };
        }
    """)

    return _filter_standalone_table_candidates(
        snapshot.get("candidates", []),
        int(snapshot.get("viewportWidth", 1920) or 1920),
        int(snapshot.get("viewportHeight", 1080) or 1080),
    )


def _filter_standalone_table_candidates(
    candidates: list[dict],
    viewport_width: int = 1920,
    viewport_height: int = 1080,
) -> list[dict]:
    valid = []
    for candidate in candidates:
        width = float(candidate.get("width", 0) or 0)
        height = float(candidate.get("height", 0) or 0)
        rows = int(candidate.get("rows", 0) or 0)
        cells = int(candidate.get("cells", 0) or 0)
        if width < 320 or height < 120:
            continue
        if width >= viewport_width * 0.98 and height >= viewport_height * 0.96:
            continue
        if rows < 3 and cells < 8:
            continue

        text = str(candidate.get("text", ""))
        signal = str(candidate.get("signal", ""))
        if _looks_like_filter_or_header(text, signal):
            continue

        valid.append({
            "x": float(candidate.get("x", 0) or 0),
            "y": float(candidate.get("y", 0) or 0),
            "width": width,
            "height": height,
            "rows": rows,
            "cells": cells,
            "tableOnly": True,
        })

    valid.sort(key=lambda box: _box_area(box), reverse=True)
    deduped = []
    for candidate in valid:
        if any(_box_iou(candidate, existing) > 0.82 for existing in deduped):
            continue
        deduped.append(candidate)

    return sorted(deduped, key=lambda b: (b["y"], b["x"]))


async def _collect_dashboard_tile_boxes(page: Page) -> list[dict]:
    """Return one crop box per dashboard tile on collection-style dashboard views."""
    snapshot: dict = await page.evaluate("""
        () => {
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

            function visible(el, r) {
                const style = window.getComputedStyle(el);
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && r.width >= 260
                    && r.height >= 140;
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

            function hasTileContent(el) {
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                return el.querySelector('svg, canvas, .ag-charts-canvas-container')
                    || /\\bNo Results?\\b/i.test(text)
                    || /(Total Cost|Cost History|Chart|\\$\\d)/i.test(text);
            }

            const candidates = [...document.querySelectorAll('div#styled-tile-dashboard')]
                .map(el => ({el, r: rectOf(el)}))
                .filter(item => visible(item.el, item.r) && hasTileContent(item.el))
                .map(item => ({
                    x: Math.max(0, item.r.left + window.scrollX),
                    y: Math.max(0, item.r.top + window.scrollY),
                    width: item.r.width,
                    height: item.r.height,
                    hasChart: !!item.el.querySelector('svg, canvas, .ag-charts-canvas-container'),
                    noResults: /\\bNo Results?\\b/i.test(item.el.innerText || ''),
                    signal: classText(item.el),
                    text: (item.el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
                }));

            return {
                viewportWidth: viewportW,
                viewportHeight: viewportH,
                candidates
            };
        }
    """)

    boxes = _filter_dashboard_tile_candidates(
        snapshot.get("candidates", []),
        int(snapshot.get("viewportWidth", 1920) or 1920),
        int(snapshot.get("viewportHeight", 1080) or 1080),
    )
    logger.info(f"  Found {len(boxes)} dashboard tile boxes")
    return boxes


def _filter_dashboard_tile_candidates(
    candidates: list[dict],
    viewport_width: int = 1920,
    viewport_height: int = 1080,
) -> list[dict]:
    valid = []
    for candidate in candidates:
        width = float(candidate.get("width", 0) or 0)
        height = float(candidate.get("height", 0) or 0)
        if width < 260 or height < 140:
            continue
        if width >= viewport_width * 0.98 and height >= viewport_height * 0.92:
            continue

        text = str(candidate.get("text", ""))
        has_chart = bool(candidate.get("hasChart"))
        no_results = bool(candidate.get("noResults"))
        has_cost_signal = bool(re.search(r"(Total Cost|Cost History|Chart|\$\d)", text, re.IGNORECASE))
        if not (has_chart or no_results or has_cost_signal):
            continue

        valid.append({
            "x": float(candidate.get("x", 0) or 0),
            "y": float(candidate.get("y", 0) or 0),
            "width": width,
            "height": height,
            "hasChart": has_chart,
            "noResults": no_results,
            "dashboardTile": True,
        })

    valid.sort(key=lambda box: _box_area(box), reverse=True)
    deduped = []
    for candidate in valid:
        if any(_box_iou(candidate, existing) > 0.82 for existing in deduped):
            continue
        deduped.append(candidate)

    return sorted(deduped, key=lambda b: (b["y"], b["x"]))


async def _collect_chart_boxes(page: Page) -> list[dict]:
    """
    Return de-duplicated bounding boxes of chart elements in document coordinates.

    Only real chart containers and valid "No results" panels are returned. Generic
    cards, filter rows, nav bars, and KPI/header-only bands are intentionally
    ignored unless they contain chart roots.
    """
    snapshot: dict = await page.evaluate("""
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
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('data-test') || ''
                ].join(' ');
            }

            function isCardLike(el) {
                return /(card|panel|paper|widget|tile|chart|graph|visual|dashboard-item|react-grid-item|grid-item|highcharts-container|recharts-wrapper|plotly|echarts|ag-charts-canvas-container|MuiPaper|chakra-card|viz|sheet|view)/i
                    .test(classText(el));
            }

            function tooPageLike(r, rootRect) {
                if (r.width >= viewportW * 0.98 && r.height >= viewportH * 0.92) return true;
                if (r.height > Math.max(rootRect.height * 3.5, rootRect.height + 520)) return true;
                if (r.width > Math.max(rootRect.width * 3.0, rootRect.width + 720)) return true;
                return false;
            }

            function boxFromRect(r, extra = {}) {
                return {
                    x: Math.max(0, r.left + window.scrollX),
                    y: Math.max(0, r.top + window.scrollY),
                    width: r.width,
                    height: r.height,
                    ...extra
                };
            }

            function horizontalOverlapRatio(a, b) {
                const left = Math.max(a.left, b.left);
                const right = Math.min(a.right, b.right);
                const overlap = Math.max(0, right - left);
                return overlap / Math.max(1, Math.min(a.width, b.width));
            }

            function isRelatedDataPanel(el, chartRect) {
                const r = rectOf(el);
                if (r.width < Math.max(320, chartRect.width * 0.55)) return false;
                if (r.height < 80 || r.height > Math.max(900, chartRect.height * 2.5)) return false;
                if (r.top < chartRect.bottom - 8) return false;
                if (r.top - chartRect.bottom > 180) return false;
                if (horizontalOverlapRatio(r, chartRect) < 0.55) return false;

                const signal = classText(el);
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                const testId = el.getAttribute('data-testid') || '';
                const tableLike =
                    el.tagName === 'TABLE' ||
                    testId === 'table-root' ||
                    /\\b(table|grid|ag-grid|data-grid|trend-table|dimension-elements|cost-table|ag-center-cols-container)\\b/i.test(signal) ||
                    ['table', 'grid', 'rowgroup'].includes(el.getAttribute('role') || '');
                const hasCostData = /(Total Cost|Cost of Change|% of Change|Dimension Elements|New Cost|\\$\\d)/i.test(text);
                return tableLike && hasCostData;
            }

            function extendWithRelatedDataPanel(chartBox, root) {
                const chartRect = {
                    left: chartBox.x - window.scrollX,
                    top: chartBox.y - window.scrollY,
                    width: chartBox.width,
                    height: chartBox.height,
                    right: chartBox.x - window.scrollX + chartBox.width,
                    bottom: chartBox.y - window.scrollY + chartBox.height
                };
                const searchRoot = root.closest('main, [role="main"], article') || document.body;
                const panels = [...searchRoot.querySelectorAll(
                    'table, [role="table"], [role="grid"], .ag-center-cols-container, [data-testid="table-root"], [class*="table" i], [class*="grid" i]'
                )].filter(el => isRelatedDataPanel(el, chartRect));

                if (!panels.length) return chartBox;
                panels.sort((a, b) => rectOf(a).top - rectOf(b).top);
                const panelRect = rectOf(panels[0]);
                const left = Math.min(chartRect.left, panelRect.left);
                const top = Math.min(chartRect.top, panelRect.top);
                const right = Math.max(chartRect.right, panelRect.right);
                const bottom = Math.max(chartRect.bottom, panelRect.bottom);

                return {
                    ...chartBox,
                    x: Math.max(0, left + window.scrollX),
                    y: Math.max(0, top + window.scrollY),
                    width: right - left,
                    height: bottom - top,
                    hasRelatedData: true
                };
            }

            function chooseGraphContainer(root) {
                const rootRect = rectOf(root);
                const cloudZeroChart = root.closest('.ag-charts-canvas-container');
                let best = cloudZeroChart || root;
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

                    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                    const controlsOnly = /(add filter|clear all|group by|time range|cost type)/i.test(text)
                        && !largeChartRootsWithin(el).length;
                    if (controlsOnly) continue;

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

                const chartBox = boxFromRect(rectOf(best), {
                    kind: 'chart',
                    hasChart: true,
                    noResults: false,
                    signal: classText(best),
                    text: (best.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
                });
                return extendWithRelatedDataPanel(chartBox, best);
            }

            function isTooLargeForCard(r) {
                return r.width >= viewportW * 0.98 && r.height >= viewportH * 0.92;
            }

            function noResultsSeed(el) {
                const r = rectOf(el);
                if (r.width < 220 || r.height < 80 || isTooLargeForCard(r)) return false;
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                return /\\bNo Results?\\b/i.test(el.getAttribute('aria-label') || '')
                    || /\\bNo results?\\b/i.test(text);
            }

            function chooseNoResultsContainer(seed) {
                let best = seed;
                for (let el = seed; el && el.tagName !== 'BODY' && el.tagName !== 'HTML'; el = el.parentElement) {
                    const r = rectOf(el);
                    if (r.width < 220 || r.height < 100 || isTooLargeForCard(r)) continue;

                    const signal = classText(el);
                    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                    const looksLikePanel =
                        el.id === 'styled-tile-dashboard' ||
                        /react-grid-item|Element__ElementCard|dashboard-tile|tile|panel|card|paper|widget/i.test(signal) ||
                        (/No results?/i.test(text) && r.height <= 520);

                    if (looksLikePanel) {
                        best = el;
                        if (el.id === 'styled-tile-dashboard' || /react-grid-item/i.test(signal)) {
                            break;
                        }
                    }
                }
                return boxFromRect(rectOf(best), {
                    kind: 'no-results',
                    hasChart: false,
                    noResults: true,
                    signal: classText(best),
                    text: (best.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
                });
            }

            const roots = [...document.querySelectorAll('svg, canvas')]
                .filter(isLargeChartRoot);

            const noResults = [...document.querySelectorAll('*')]
                .filter(noResultsSeed)
                .map(chooseNoResultsContainer);

            const candidates = [
                ...roots.map(chooseGraphContainer),
                ...noResults,
            ].filter(b => b.width >= MIN_W && b.height >= 80);

            return {
                viewportWidth: viewportW,
                viewportHeight: viewportH,
                candidates
            };
        }
    """)

    boxes = _filter_chart_box_candidates(
        snapshot.get("candidates", []),
        int(snapshot.get("viewportWidth", 1920) or 1920),
        int(snapshot.get("viewportHeight", 1080) or 1080),
    )
    logger.info(f"  Found {len(boxes)} chart bounding boxes")
    return boxes


def _filter_chart_box_candidates(
    candidates: list[dict],
    viewport_width: int = 1920,
    viewport_height: int = 1080,
) -> list[dict]:
    """Filter and de-duplicate raw DOM candidates into reliable chart crop boxes."""
    valid = []
    for candidate in candidates:
        width = float(candidate.get("width", 0) or 0)
        height = float(candidate.get("height", 0) or 0)
        if width < 180 or height < 80:
            continue
        if width >= viewport_width * 0.98 and height >= viewport_height * 0.92:
            continue

        has_chart = bool(candidate.get("hasChart"))
        no_results = bool(candidate.get("noResults"))
        if not has_chart and not no_results:
            continue

        text = str(candidate.get("text", ""))
        signal = str(candidate.get("signal", ""))
        header_or_filter_only = (
            not has_chart
            and not no_results
            and _looks_like_filter_or_header(text, signal)
        )
        if header_or_filter_only:
            continue

        valid.append({
            "x": float(candidate.get("x", 0) or 0),
            "y": float(candidate.get("y", 0) or 0),
            "width": width,
            "height": height,
            "hasChart": has_chart,
            "noResults": no_results,
            "hasRelatedData": bool(candidate.get("hasRelatedData")),
        })

    valid.sort(key=lambda box: _box_area(box), reverse=True)
    deduped = []
    for candidate in valid:
        if any(_box_iou(candidate, existing) > 0.82 for existing in deduped):
            continue
        deduped.append(candidate)

    graph_boxes = [
        candidate for candidate in deduped
        if sum(
            1 for other in deduped
            if other is not candidate and _box_contains(candidate, other)
        ) < 2
    ]

    return sorted(graph_boxes, key=lambda b: (b["y"], b["x"]))


def _looks_like_filter_or_header(text: str, signal: str) -> bool:
    combined = f"{text} {signal}"
    return bool(
        re.search(
            r"(add filter|clear all|group by|time range|cost type|create insight|export|navbar|toolbar)",
            combined,
            re.IGNORECASE,
        )
    )


def _box_area(box: dict) -> float:
    return float(box.get("width", 0) or 0) * float(box.get("height", 0) or 0)


def _box_iou(a: dict, b: dict) -> float:
    left = max(float(a["x"]), float(b["x"]))
    top = max(float(a["y"]), float(b["y"]))
    right = min(float(a["x"]) + float(a["width"]), float(b["x"]) + float(b["width"]))
    bottom = min(float(a["y"]) + float(a["height"]), float(b["y"]) + float(b["height"]))
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0
    return intersection / (_box_area(a) + _box_area(b) - intersection)


def _box_contains(outer: dict, inner: dict, tolerance: float = 12.0) -> bool:
    return (
        float(outer["x"]) <= float(inner["x"]) + tolerance
        and float(outer["y"]) <= float(inner["y"]) + tolerance
        and float(outer["x"]) + float(outer["width"]) >= float(inner["x"]) + float(inner["width"]) - tolerance
        and float(outer["y"]) + float(outer["height"]) >= float(inner["y"]) + float(inner["height"]) - tolerance
    )


def _crop_graphs_from_full_page(
    full_page_path: Path,
    boxes: list[dict],
    output_dir: Path,
    padding: int = 8,
    css_size: dict | None = None,
) -> list[Path]:
    """
    Crop each bounding box out of the full-page PNG.

    Args:
        full_page_path: Path to 000_full_page.png
        boxes: List of {x, y, width, height} dicts (document coordinates)
        output_dir: Directory to write cropped PNGs into
        padding: Extra CSS pixels added on each side of the crop (default 8)
        css_size: Full-page CSS coordinate size used to scale into PNG pixels

    Returns:
        List of paths to the cropped PNG files, in top-to-bottom order.
    """
    try:
        img = Image.open(full_page_path)
    except Exception as e:
        raise ScreenshotCaptureError(f"Failed to open full-page image {full_page_path}: {e}") from e
    img_w, img_h = img.size
    css_w = max(1, int((css_size or {}).get("width") or img_w))
    css_h = max(1, int((css_size or {}).get("height") or img_h))
    scale_x = img_w / css_w
    scale_y = img_h / css_h

    # Sort top-to-bottom so numbering matches visual order on the page
    sorted_boxes = sorted(boxes, key=lambda b: b["y"])

    crops: list[Path] = []
    for idx, b in enumerate(sorted_boxes, start=1):
        left = max(0, int((float(b["x"]) - padding) * scale_x))
        top = max(0, int((float(b["y"]) - padding) * scale_y))
        right = min(img_w, int((float(b["x"]) + float(b["width"]) + padding) * scale_x))
        bottom = min(img_h, int((float(b["y"]) + float(b["height"]) + padding) * scale_y))

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
