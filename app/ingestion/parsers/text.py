from app.ingestion.parsers.base import DocumentParsingError, ParsedSection


class PlainTextParser:
    def parse(self, content: bytes) -> list[ParsedSection]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParsingError("The text file is not valid UTF-8") from exc
        return [ParsedSection(text=text)]
