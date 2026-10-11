from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.ingestion.parsers.base import DocumentParsingError, ParsedSection


class PdfParser:
    def parse(self, content: bytes) -> list[ParsedSection]:
        try:
            reader = PdfReader(BytesIO(content))
            return [
                ParsedSection(
                    text=page.extract_text() or "",
                    page_number=page_number,
                )
                for page_number, page in enumerate(reader.pages, start=1)
            ]
        except (OSError, PyPdfError, ValueError) as exc:
            raise DocumentParsingError("The PDF could not be parsed") from exc
