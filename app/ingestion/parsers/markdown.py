import re

from app.ingestion.parsers.base import DocumentParsingError, ParsedSection

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class MarkdownParser:
    def parse(self, content: bytes) -> list[ParsedSection]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParsingError("The Markdown file is not valid UTF-8") from exc

        sections: list[ParsedSection] = []
        current_title: str | None = None
        current_lines: list[str] = []

        def append_section() -> None:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append(
                    ParsedSection(text=body, section_title=current_title)
                )

        for line in text.splitlines():
            heading = HEADING_PATTERN.match(line)
            if heading is None:
                current_lines.append(line)
                continue
            append_section()
            current_title = heading.group(2).strip()
            current_lines = []

        append_section()
        return sections
