from dataclasses import dataclass
from typing import Protocol


class DocumentParsingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ParsedSection:
    text: str
    page_number: int | None = None
    section_title: str | None = None


class DocumentParser(Protocol):
    def parse(self, content: bytes) -> list[ParsedSection]: ...
