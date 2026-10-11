from dataclasses import dataclass
import re

from app.ingestion.parsers import ParsedSection


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    page_number: int | None
    section_title: str | None


def normalize_text(text: str) -> str:
    normalized_lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(normalized_lines)).strip()


class RecursiveTextChunker:
    _separators = ("\n\n", "\n", ". ", " ", "")

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError(
                "chunk_overlap must be nonnegative and smaller than chunk_size"
            )
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._content_size = chunk_size - chunk_overlap

    def chunk_sections(self, sections: list[ParsedSection]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for section in sections:
            text = normalize_text(section.text)
            if not text:
                continue
            for chunk_text in self._split(text):
                chunks.append(
                    TextChunk(
                        text=chunk_text,
                        page_number=section.page_number,
                        section_title=section.section_title,
                    )
                )
        return chunks

    def _split(self, text: str) -> list[str]:
        pieces = self._recursive_split(text, 0)
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip() if current else piece
            if len(candidate) <= self._content_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
                overlap_length = min(
                    self._chunk_overlap,
                    max(0, self._chunk_size - len(piece) - 1),
                )
                overlap = current[-overlap_length:] if overlap_length else ""
                candidate = f"{overlap} {piece}".strip()
            current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _recursive_split(self, text: str, separator_index: int) -> list[str]:
        if len(text) <= self._content_size:
            return [text]
        separator = self._separators[separator_index]
        if separator == "":
            return [
                text[index : index + self._content_size]
                for index in range(0, len(text), self._content_size)
            ]
        if separator == ". ":
            parts = [
                part.strip()
                for part in re.split(r"(?<=\.)\s+", text)
                if part.strip()
            ]
        else:
            parts = [
                part.strip() for part in text.split(separator) if part.strip()
            ]
        if len(parts) == 1:
            return self._recursive_split(text, separator_index + 1)
        result: list[str] = []
        for part in parts:
            result.extend(self._recursive_split(part, separator_index + 1))
        return result
