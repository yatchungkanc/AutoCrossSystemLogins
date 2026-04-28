import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import graph_report
from src.analysis import build_analysis_prompt
from src.graph_inputs import GraphInput, GraphInputError, parse_graph_sources, parse_graph_specs
from src.report_generator import generate_html_report


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


if __name__ == "__main__":
    unittest.main()
