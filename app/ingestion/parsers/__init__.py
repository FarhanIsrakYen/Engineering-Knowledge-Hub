from app.ingestion.parsers.base import (
    DocumentParser,
    DocumentParsingError,
    ParsedSection,
)
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import PdfParser
from app.ingestion.parsers.text import PlainTextParser

PARSERS: dict[str, DocumentParser] = {
    "application/pdf": PdfParser(),
    "text/markdown": MarkdownParser(),
    "text/plain": PlainTextParser(),
}


def get_parser(content_type: str) -> DocumentParser:
    try:
        return PARSERS[content_type]
    except KeyError as exc:
        raise DocumentParsingError(
            f"No parser is available for content type {content_type}"
        ) from exc


__all__ = [
    "DocumentParser",
    "DocumentParsingError",
    "ParsedSection",
    "get_parser",
]
