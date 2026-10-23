"""A document's page layout: its lines and their column cells (word-level reconstruction).

Plain-language summary: reading a PDF, an OCR result or a text lays the document out as numbered lines, each with the
cells the columns make. The candidate finders, the questions to the models and the source references of the review
page all read these lines. 209 (plan G-process-core R2d): the classes moved here from the AI layer's data model
(`jav/ai/models.py`), because reading, which makes them, sits below it; a saved flow state that names them at their
earlier place is read with them here (`jav/flows/persistence.py` `MOVED_CLASSES`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CellLayout(BaseModel):
    text: str
    x0: float
    x1: float


class LineLayout(BaseModel):
    no: int  # 1-based, document-wide
    page: int
    text: str  # cells joined with 3 spaces; this goes into the JEV state
    cells: list[CellLayout] = Field(default_factory=list)


__all__ = ["CellLayout", "LineLayout"]
