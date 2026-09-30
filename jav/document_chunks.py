"""Lossless text chunks, carrying the page data of the existing PDF/OCR lines.

Source splitting only: walking through a chunk does not prove complete data extraction.
Follows the overlapping-window principle of the source finder, with explicit splitting of long lines.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jav.document_learning import digest
from jav.models import LineLayout
from jav.config import PROJECT_ROOT


def load_chunk_config():
    return json.loads((PROJECT_ROOT/'configs/experiments/document_chunks.json').read_text(encoding='utf-8'))


class ChunkPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_chars: int = Field(ge=1, le=16000)
    overlap_chars: int = Field(ge=0)
    max_chunks: int = Field(ge=1, le=10000)

    @model_validator(mode='after')
    def valid_overlap(self):
        if self.overlap_chars >= self.max_chars:
            raise ValueError('overlap_chars must be smaller than max_chars')
        return self


class SourceChunk(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    section_id: str
    page: int | None
    start: int
    end: int
    source_sha256: str
    hard_split: bool


class DocumentPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    source_sha256: str
    source_chars: int
    policy: ChunkPolicy
    chunks: list[SourceChunk]
    coverage_complete: bool = True


def plan_document(text: str, policy: ChunkPolicy, *, layout: list[LineLayout] | None = None) -> DocumentPlan:
    """The plan covers the whole text; when the chunk limit is exceeded there is no partial plan.

    Page numbers are taken only from line data verified against the same text.
    section_id is a technical sub-identifier, not a recognised business document boundary.
    """
    policy = ChunkPolicy.model_validate(policy.model_dump())
    if not text.strip():
        raise ValueError('source empty')
    sections = [(0, len(text), None)]
    if layout is not None:
        if (not layout or '\n'.join(row.text for row in layout) != text
                or any(row.page < 1 or row.no < 1 for row in layout)
                or any(b.page < a.page or b.no <= a.no for a,b in zip(layout,layout[1:]))):
            raise ValueError('layout does not match ordered source lines')
        sections, offset, start, page = [], 0, 0, layout[0].page
        for index, row in enumerate(layout):
            if row.page != page:
                sections.append((start, offset, page))
                start, page = offset, row.page
            offset += len(row.text) + (index < len(layout)-1)
        sections.append((start, len(text), page))
    chunks = []
    for section_index, (left, right, page) in enumerate(sections, 1):
        start = left
        while start < right:
            end = min(start + policy.max_chars, right)
            hard_split = False
            if end < right:
                boundary = text.rfind('\n', start + policy.overlap_chars + 1, end)
                if boundary >= 0:
                    end = boundary + 1
                else:
                    hard_split = True
            chunks.append(SourceChunk(id=f'C{len(chunks)+1:06d}',section_id=f'S{section_index:06d}',
                page=page,start=start,end=end,source_sha256=digest(text[start:end]),hard_split=hard_split))
            if len(chunks) > policy.max_chunks:
                raise ValueError('source exceeds max_chunks; no requests were sent')
            if end == right:
                break
            start = end - policy.overlap_chars
    return DocumentPlan(source_sha256=digest(text),source_chars=len(text),policy=policy,chunks=chunks)
