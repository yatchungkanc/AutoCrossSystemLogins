"""Graph input parsing and validation for generic report generation."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class GraphInputError(ValueError):
    """Raised when graph input arguments are invalid."""
    pass


@dataclass(frozen=True)
class GraphInput:
    """A named graph image supplied by the caller."""

    name: str
    path: Path


@dataclass(frozen=True)
class GraphSource:
    """A named graph source supplied by the caller.

    The source may be either a local image file or a URL that must be captured
    before analysis.
    """

    name: str
    value: str
    path: Path | None = None
    url: str | None = None

    @property
    def is_url(self) -> bool:
        return self.url is not None


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_graph_spec(spec: str) -> GraphInput:
    """Parse a single CLI graph spec in the form 'Display Name=/path/to/image'."""
    source = parse_graph_source(spec)
    if source.path is None:
        raise GraphInputError(
            "Graph input must be a local image path for this operation."
        )
    return GraphInput(name=source.name, path=source.path)


def parse_graph_source(spec: str) -> GraphSource:
    """Parse a single CLI graph spec in the form 'Display Name=/path-or-url'."""
    if "=" not in spec:
        raise GraphInputError(
            "Graph input must use the format 'Name=/path/to/image-or-url'."
        )

    name, raw_value = spec.split("=", 1)
    name = name.strip()
    raw_value = raw_value.strip()

    if not name:
        raise GraphInputError("Graph name cannot be empty.")
    if not raw_value:
        raise GraphInputError(f"Graph path cannot be empty for '{name}'.")

    if _is_url(raw_value):
        return GraphSource(name=name, value=raw_value, url=raw_value)

    path = Path(raw_value).expanduser()
    if not path.exists():
        raise GraphInputError(f"Graph path does not exist for '{name}': {path}")
    if not path.is_file():
        raise GraphInputError(f"Graph path is not a file for '{name}': {path}")

    return GraphSource(name=name, value=raw_value, path=path.resolve())


def parse_graph_specs(specs: list[str]) -> list[GraphInput]:
    """Parse and validate a list of graph specs."""
    sources = parse_graph_sources(specs)
    url_sources = [source for source in sources if source.is_url]
    if url_sources:
        raise GraphInputError("URL graph inputs must be captured before analysis.")

    return [
        GraphInput(name=source.name, path=source.path)
        for source in sources
        if source.path is not None
    ]


def parse_graph_sources(specs: list[str]) -> list[GraphSource]:
    """Parse and validate local image or URL graph source specs."""
    if not specs:
        raise GraphInputError("At least one --graph value is required.")

    sources = [parse_graph_source(spec) for spec in specs]
    seen_names: set[str] = set()
    for source in sources:
        key = source.name.casefold()
        if key in seen_names:
            raise GraphInputError(f"Duplicate graph name: {source.name}")
        seen_names.add(key)

    return sources
