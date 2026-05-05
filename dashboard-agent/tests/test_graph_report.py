import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import graph_report
from src import screenshot_capture
from src.analysis import build_analysis_prompt
from src.graph_inputs import GraphInput, GraphInputError, parse_graph_sources, parse_graph_specs
from src.report_generator import generate_html_report
from src.screenshot_capture import ScreenshotCaptureError


class GraphInputParsingTests(unittest.TestCase):
    def test_parse_multiple_named_graphs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            second = Path(tmp) / "second.png"
            first.write_text("first")
            second.write_text("second")

            graphs = parse_graph_specs([
                f"First Graph={first}",
                f"Second Graph={second}",
            ])

            self.assertEqual([g.name for g in graphs], ["First Graph", "Second Graph"])
            self.assertEqual([g.path for g in graphs], [first.resolve(), second.resolve()])

    def test_rejects_missing_separator(self) -> None:
        with self.assertRaises(GraphInputError):
            parse_graph_specs(["No separator"])

    def test_rejects_empty_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / "graph.png"
            graph.write_text("graph")

            with self.assertRaises(GraphInputError):
                parse_graph_specs([f"={graph}"])

    def test_rejects_missing_path(self) -> None:
        with self.assertRaises(GraphInputError):
            parse_graph_specs(["Graph="])

    def test_rejects_duplicate_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / "graph.png"
            graph.write_text("graph")

            with self.assertRaises(GraphInputError):
                parse_graph_specs([f"Graph={graph}", f"graph={graph}"])

    def test_parse_url_graph_source(self) -> None:
        sources = parse_graph_sources([
            "Forecast=https://example.com/report?view=cost&month=2026-04"
        ])

        self.assertEqual(sources[0].name, "Forecast")
        self.assertTrue(sources[0].is_url)
        self.assertEqual(
            sources[0].url,
            "https://example.com/report?view=cost&month=2026-04",
        )

    def test_path_only_parser_rejects_urls(self) -> None:
        with self.assertRaises(GraphInputError):
            parse_graph_specs(["Forecast=https://example.com/report"])


class GraphAnalysisPromptTests(unittest.TestCase):
    def test_prompt_uses_graph_names_and_focus_without_cloudhealth(self) -> None:
        prompts_config = {
            "analysis_prompt": {
                "system": "Analyze graphs. Avoid product assumptions.",
                "user_template": (
                    "Info:\n{report_info}\n"
                    "Count: {graph_count}\n"
                    "Graphs:\n{graph_list}\n"
                    "{focus_instruction}"
                ),
            },
            "focus_instructions": {
                "custom_template": "Focus area: {focus_area}",
            },
        }
        graph = GraphInput(name="Budget Forecast", path=Path("/tmp/budget.png"))

        prompt = build_analysis_prompt(
            prompts_config,
            [graph],
            {"title": "Finance Review", "captured_at": "2026-04-28 10:00:00"},
            ["variance"],
        )

        self.assertIn("Graph ID: G001", prompt)
        self.assertIn("Graph name: Budget Forecast", prompt)
        self.assertIn("Image path: /tmp/budget.png", prompt)
        self.assertIn("Focus area: variance", prompt)
        self.assertNotIn("CloudHealth", prompt)


class GraphReportGenerationTests(unittest.TestCase):
    def test_report_embeds_image_but_displays_graph_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graph_path = tmp_path / "source-file.png"
            graph_path.write_text("fake image")
            template_path = tmp_path / "template.html"
            output_path = tmp_path / "graph_report.html"
            template_path.write_text(
                "<h1>{{report_name}}</h1>"
                "<div>{{graph_count}}</div>"
                "<main>{{content}}</main>"
            )

            generate_html_report(
                template_path,
                "\n".join([
                    "### Graph Analysis",
                    "",
                    "| Graph | Scope / Time Range | Key Values | Trend | Observations |",
                    "|---|---|---|---|---|",
                    "| Budget Forecast | Q1 | 42 | increasing | [INFO] visible |",
                ]),
                {"title": "Finance Review"},
                output_path,
                graph_inputs=[GraphInput(name="Budget Forecast", path=graph_path)],
            )

            html = output_path.read_text()
            assets = list((tmp_path / "graph_report_graphs").glob("*.png"))

            self.assertEqual(len(assets), 1)
            self.assertIn("Finance Review", html)
            self.assertIn("<div>1</div>", html)
            self.assertIn(">Budget Forecast</span>", html)
            self.assertNotIn(">source-file.png</span>", html)

    def test_report_embeds_by_graph_id_without_filename_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            all_products = tmp_path / "all.png"
            product_a = tmp_path / "product-a.png"
            all_products.write_text("all")
            product_a.write_text("a")
            template_path = tmp_path / "template.html"
            output_path = tmp_path / "graph_report.html"
            template_path.write_text(
                "<h1>{{report_name}}</h1>"
                "<div>{{graph_count}}</div>"
                "<main>{{content}}</main>"
            )

            generate_html_report(
                template_path,
                "\n".join([
                    "### Graph Analysis",
                    "",
                    "| Graph | Scope / Time Range | Key Values | Trend | Observations |",
                    "|---|---|---|---|---|",
                    "| G002 | Q1 | 42 | increasing | [INFO] visible |",
                    "| Product | Q1 | N/A | N/A | [INFO] unmatched label |",
                    "",
                    "### Executive Summary",
                    "",
                    "| Category | Finding | Severity |",
                    "|---|---|---|",
                    "| Overall Pattern | Stable | [INFO] |",
                ]),
                {"title": "Finance Review"},
                output_path,
                graph_inputs=[
                    GraphInput(name="All Products", path=all_products),
                    GraphInput(name="Product A", path=product_a),
                ],
            )

            html = output_path.read_text()

            self.assertIn('src="graph_report_graphs/002_Product_A.png"', html)
            self.assertIn(">Product A</span>", html)
            self.assertIn(">Product</span>", html)
            self.assertEqual(html.count("graph-thumb"), 1)


class GraphReportAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_url_sources_to_individual_captured_graphs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_path = tmp_path / "local.png"
            first_capture = tmp_path / "001_graph_0.png"
            second_capture = tmp_path / "002_graph_1.png"
            local_path.write_text("local")
            first_capture.write_text("first")
            second_capture.write_text("second")

            sources = parse_graph_sources([
                f"Local Graph={local_path}",
                "Dashboard=https://example.com/dashboard",
            ])
            agent = graph_report.GraphReportAgent(sources=sources)

            with (
                patch.object(graph_report, "TEMP_DIR", tmp_path / "captures"),
                patch.object(
                    graph_report,
                    "capture_graphs_from_url",
                    new=AsyncMock(return_value=([first_capture, second_capture], {})),
                ) as capture_mock,
            ):
                graphs = await agent._resolve_graph_inputs()

            self.assertEqual(
                [graph.name for graph in graphs],
                ["Local Graph", "Dashboard - Graph 1", "Dashboard - Graph 2"],
            )
            capture_mock.assert_awaited_once()

    async def test_skips_failed_url_source_when_other_graphs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_path = tmp_path / "local.png"
            local_path.write_text("local")

            sources = parse_graph_sources([
                f"Local Graph={local_path}",
                "Broken Dashboard=https://example.com/dashboard",
            ])
            agent = graph_report.GraphReportAgent(sources=sources)

            with (
                patch.object(graph_report, "TEMP_DIR", tmp_path / "captures"),
                patch.object(
                    graph_report,
                    "capture_graphs_from_url",
                    new=AsyncMock(side_effect=ScreenshotCaptureError("no charts")),
                ),
            ):
                graphs = await agent._resolve_graph_inputs()

        self.assertEqual([graph.name for graph in graphs], ["Local Graph"])
        self.assertEqual(agent.skipped_sources, [("Broken Dashboard", "no charts")])

    async def test_all_failed_url_sources_raise_graph_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sources = parse_graph_sources([
                "Broken Dashboard=https://example.com/dashboard",
            ])
            agent = graph_report.GraphReportAgent(sources=sources)

            with (
                patch.object(graph_report, "TEMP_DIR", tmp_path / "captures"),
                patch.object(
                    graph_report,
                    "capture_graphs_from_url",
                    new=AsyncMock(side_effect=ScreenshotCaptureError("no charts")),
                ),
            ):
                with self.assertRaises(GraphInputError):
                    await agent._resolve_graph_inputs()

    async def test_multi_chart_url_names_remain_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first_capture = tmp_path / "001_graph_0.png"
            second_capture = tmp_path / "002_graph_1.png"
            first_capture.write_text("first")
            second_capture.write_text("second")

            sources = parse_graph_sources([
                "Dashboard=https://example.com/dashboard",
            ])
            agent = graph_report.GraphReportAgent(sources=sources)

            with (
                patch.object(graph_report, "TEMP_DIR", tmp_path / "captures"),
                patch.object(
                    graph_report,
                    "capture_graphs_from_url",
                    new=AsyncMock(return_value=([first_capture, second_capture], {})),
                ),
            ):
                graphs = await agent._resolve_graph_inputs()

        self.assertEqual(
            [graph.name for graph in graphs],
            ["Dashboard - Graph 1", "Dashboard - Graph 2"],
        )


class ScreenshotCaptureSelectionTests(unittest.TestCase):
    def test_url_match_accepts_exact_url(self) -> None:
        url = "https://app.cloudzero.com/analytics/dashboards/32955/view"

        self.assertGreater(screenshot_capture._url_match_score(url, url), 0)

    def test_url_match_accepts_query_reordering_and_extra_query(self) -> None:
        requested = "https://app.cloudzero.com/explorer?activeCostType=amortized_cost&granularity=monthly"
        existing = "https://app.cloudzero.com/explorer?showRightFlyout=filters&granularity=monthly&activeCostType=amortized_cost"

        self.assertGreater(screenshot_capture._url_match_score(requested, existing), 0)

    def test_url_match_accepts_tableau_hash_mutation(self) -> None:
        requested = (
            "https://eu-west-1a.online.tableau.com/#/site/elseviertableau/"
            "views/Security/AWSAccountVulnerabilityTrends?:iid=1"
        )
        existing = (
            "https://eu-west-1a.online.tableau.com/#/site/elseviertableau/"
            "views/Security/AWSAccountVulnerabilityTrends?:iid=7"
        )

        self.assertGreater(screenshot_capture._url_match_score(requested, existing), 0)

    def test_dashboard_view_url_detection(self) -> None:
        self.assertTrue(
            screenshot_capture._is_dashboard_view_url(
                "https://app.cloudzero.com/analytics/dashboards/32955/view"
            )
        )
        self.assertFalse(
            screenshot_capture._is_dashboard_view_url(
                "https://app.cloudzero.com/explorer?activeCostType=discounted_amortized_cost"
            )
        )

    def test_filter_dashboard_tiles_accepts_styled_tile_graphs(self) -> None:
        boxes = screenshot_capture._filter_dashboard_tile_candidates([
            {
                "x": 10,
                "y": 20,
                "width": 800,
                "height": 420,
                "hasChart": True,
                "text": "Cost History by Product",
            },
            {
                "x": 850,
                "y": 20,
                "width": 800,
                "height": 420,
                "text": "No Results",
                "noResults": True,
            },
        ])

        self.assertEqual(len(boxes), 2)
        self.assertTrue(all(box["dashboardTile"] for box in boxes))

    def test_filter_dashboard_tiles_rejects_non_graph_tile_shells(self) -> None:
        boxes = screenshot_capture._filter_dashboard_tile_candidates([
            {
                "x": 10,
                "y": 20,
                "width": 800,
                "height": 420,
                "text": "Tile actions Edit Duplicate",
            },
        ])

        self.assertEqual(boxes, [])

    def test_filter_candidates_accepts_multiple_chart_containers(self) -> None:
        boxes = screenshot_capture._filter_chart_box_candidates([
            {"x": 10, "y": 20, "width": 600, "height": 300, "hasChart": True},
            {"x": 10, "y": 380, "width": 600, "height": 300, "hasChart": True},
        ])

        self.assertEqual(len(boxes), 2)

    def test_filter_candidates_accepts_no_results_panel(self) -> None:
        boxes = screenshot_capture._filter_chart_box_candidates([
            {"x": 10, "y": 20, "width": 600, "height": 180, "noResults": True},
        ])

        self.assertEqual(len(boxes), 1)

    def test_filter_candidates_rejects_header_only_panel(self) -> None:
        boxes = screenshot_capture._filter_chart_box_candidates([
            {
                "x": 10,
                "y": 20,
                "width": 1200,
                "height": 180,
                "text": "Add Filter Account Name Group By Time Range Cost Type",
            },
        ])

        self.assertEqual(boxes, [])

    def test_crop_scales_css_boxes_to_device_pixel_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            full_page = tmp_path / "full.png"
            img = Image.new("RGB", (400, 400), "white")
            for x in range(100, 300):
                for y in range(200, 320):
                    img.putpixel((x, y), (20, 120, 200))
            img.save(full_page)

            crops = screenshot_capture._crop_graphs_from_full_page(
                full_page,
                [{"x": 50, "y": 100, "width": 100, "height": 60}],
                tmp_path,
                padding=0,
                css_size={"width": 200, "height": 200},
            )

            crop = Image.open(crops[0])
            self.assertEqual(crop.size, (200, 120))
            self.assertEqual(crop.getpixel((20, 20)), (20, 120, 200))


class DashboardGroupSourceTests(unittest.TestCase):
    def test_parser_accepts_positional_dashboard_groups(self) -> None:
        args = graph_report.build_arg_parser().parse_args([
            "ops-metrics",
            "cloudzero-dashboard",
        ])

        self.assertEqual(args.groups, ["ops-metrics", "cloudzero-dashboard"])

    def test_resolves_dashboard_groups_to_url_sources(self) -> None:
        dashboards = [
            {
                "id": "ops-metrics",
                "name": "AWS Account Vulnerability Trends",
                "url": "https://example.com/tableau",
                "auth_type": "email_only",
            },
            {
                "id": "ops-metrics",
                "name": "AWS Account Vulnerability Age Breakdown",
                "url": "https://example.com/tableau-age",
                "auth_type": "email_only",
            },
        ]

        with patch.object(graph_report, "load_dashboards", return_value=dashboards):
            sources = graph_report.graph_sources_from_dashboard_groups(["ops-metrics"])

        self.assertEqual(
            [source.name for source in sources],
            [
                "ops-metrics: AWS Account Vulnerability Trends",
                "ops-metrics: AWS Account Vulnerability Age Breakdown",
            ],
        )
        self.assertTrue(all(source.is_url for source in sources))

    def test_resolve_graph_sources_accepts_graphs_and_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "local.png"
            local_path.write_text("local")
            dashboards = [
                {
                    "id": "cloudzero-dashboard",
                    "name": "CloudZero Cost History",
                    "url": "https://example.com/cloudzero",
                    "auth_type": "cloudzero",
                },
            ]

            with patch.object(graph_report, "load_dashboards", return_value=dashboards):
                sources = graph_report.resolve_graph_sources(
                    [f"Local Graph={local_path}"],
                    ["cloudzero-dashboard"],
                )

        self.assertEqual(
            [source.name for source in sources],
            ["Local Graph", "cloudzero-dashboard: CloudZero Cost History"],
        )

    def test_rejects_empty_graph_report_inputs(self) -> None:
        with self.assertRaises(GraphInputError):
            graph_report.resolve_graph_sources([], [])

    def test_rejects_unmatched_dashboard_group(self) -> None:
        with patch.object(graph_report, "load_dashboards", return_value=[]):
            with self.assertRaises(GraphInputError):
                graph_report.graph_sources_from_dashboard_groups(["missing"])


if __name__ == "__main__":
    unittest.main()
