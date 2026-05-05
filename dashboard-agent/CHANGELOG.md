# Changelog

## 2026-05-05 - Deterministic Graph Image Linking

### Changes
**Critical Fix:** Replaced graph-label-to-image guessing with deterministic graph IDs so each analysis row links to the exact graph image that was analyzed.

#### Previous Issues
- Filename and label matching could map multiple different analysis rows to the same image.
- Generic labels such as "All Products" could be confused with more specific product graphs.
- Summary table rows could be treated as graph rows and sent through image matching.
- The matching behavior became difficult to reason about because display relied on similarity heuristics after analysis had already completed.

#### New Approach
Each graph now receives a stable analysis ID (`G001`, `G002`, etc.) based on the resolved graph input order. The analysis prompt asks Copilot to use those exact IDs in the `Graph` column, and report generation uses an exact ID-to-image map when embedding thumbnails.

#### Technical Details
- Added `graph_id` support to `GraphInput` plus `graph_analysis_id()` for default IDs.
- `analysis.py` includes both `Graph ID` and friendly `Graph name` in the prompt.
- `prompts.yaml` requires exact Graph IDs in the analysis table.
- `report_generator.py` uses exact mappings only; unknown labels render as text and log a warning instead of guessing.
- Non-graph tables, such as the Executive Summary, no longer try to embed graph thumbnails.

#### Benefits
- ✅ Each graph analysis links to the image that was actually analyzed
- ✅ Eliminates duplicate thumbnails caused by label/filename similarity
- ✅ Keeps report display names friendly while using IDs for internal linking
- ✅ Fails visibly on malformed analysis output instead of silently choosing the wrong image

### Files Modified
- `dashboard-agent/config/prompts.yaml`
- `dashboard-agent/src/analysis.py`
- `dashboard-agent/src/graph_inputs.py`
- `dashboard-agent/src/report_generator.py`
- `dashboard-agent/tests/test_graph_report.py`

---

## 2026-05-05 - CloudZero Layout Update

### Changes
Updated screenshot capture module to support the new CloudZero layout on `next.cloudzero.com`:

#### New Layout Structure
- **Old (app.cloudzero.com)**: Standard scrollable containers
- **New (next.cloudzero.com)**: 
  - Main container: `<main data-scroll-container="main">`
  - Graph containers: `<div class="chakra-card__root">`
  - Data tables: `<div data-testid="table-root" class="chakra-card_root">`

#### Code Updates
1. **Scroll Container Detection** (`_mark_scroll_container`):
   - Now prioritizes `main[data-scroll-container="main"]` for CloudZero next layout
   - Falls back to generic scroll container detection for backwards compatibility
   
2. **Data Panel Detection** (`isRelatedDataPanel`):
   - Added `data-testid="table-root"` detection for new table structure
   - Maintains compatibility with existing table detection patterns

3. **Query Selectors** (`extendWithRelatedDataPanel`):
   - Added `[data-testid="table-root"]` to panel search queries
   - Ensures new Chakra UI tables are properly detected and merged with charts

### Compatibility
- ✅ `app.cloudzero.com` - Legacy layout still supported
- ✅ `next.cloudzero.com` - New Chakra UI layout fully supported
- ✅ All other dashboards - No impact

### Files Modified
- `dashboard-agent/src/screenshot_capture.py`
