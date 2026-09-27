"""Deliverable generation.

Turns extracted findings into real .docx, .pptx and .xlsx files rather than a
chat reply someone then has to retype. All three libraries write Office Open
XML locally with no service call, which is what makes this possible at all in
an air-gapped deployment.

Files land in backend/data/generated/ under a slugged, timestamped name and
are served read-only by GET /files/{filename}.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.util import Inches, Pt as PptPt

from app.core.logs import get_file_logger

log = get_file_logger("drishti.documents", "documents.log")

# backend/app/services/document_generator.py -> backend/
GENERATED_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "generated"

# Warm off-black and the rust accent, matching the interface. Kept here rather
# than imported so the generator has no dependency on frontend theming.
INK: Final = RGBColor(0x2B, 0x27, 0x25)
ACCENT_HEX: Final = "C15F3C"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Keys a model plausibly uses when it decides to send a structured object where
# a string was asked for. Ordered by how likely each is to hold the real text.
_TEXT_KEYS: Final = (
    "description", "text", "finding", "summary", "detail", "content",
    "observation", "value", "item",
)


def _as_text(item: Any) -> str:
    """Coerce whatever the model sent into a readable line.

    Schemas are a request, not a guarantee. Asked for a list of strings, a
    model will sometimes send a list of objects instead — and stringifying one
    of those puts a raw Python dict into a document a human is meant to sign.
    Pulling the meaningful field out is the difference between a usable
    deliverable and an obviously machine-generated one.
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in _TEXT_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        # No recognised key: join the scalar values rather than losing the row.
        joined = " ".join(
            str(v).strip() for v in item.values() if isinstance(v, (str, int, float))
        )
        return joined.strip()
    if isinstance(item, (list, tuple)):
        return " ".join(_as_text(part) for part in item).strip()
    return str(item).strip()


class DocumentGenerationError(RuntimeError):
    """The document could not be built."""


def _slug(text: str, fallback: str) -> str:
    slug = _SLUG_STRIP.sub("-", (text or "").lower()).strip("-")
    return (slug or fallback)[:60]


def _destination(title: str, suffix: str, fallback: str) -> Path:
    """A collision-proof path inside the generated directory.

    The timestamp makes files sort chronologically and the short uuid stops
    two documents generated in the same second from overwriting each other.
    """
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return GENERATED_DIR / f"{_slug(title, fallback)}-{stamp}-{uuid.uuid4().hex[:6]}{suffix}"


def _record(
    kind: str,
    path: Path,
    items: int,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    # Metadata only, consistent with the other audit logs: the document
    # content is in the document.
    log.info(
        "kind=%s | file=%s | items=%d | bytes=%d",
        kind, path.name, items, path.stat().st_size,
    )
    try:
        from app.services.audit_service import record_event

        record_event(
            "document_generated",
            user_id or "demo_user",
            f"{kind}: {path.name} ({items} item(s), {path.stat().st_size} bytes)",
            thread_id=thread_id,
            source_component="document_generator.py",
        )
    except Exception as exc:
        log.warning("audit recording failed: %s", exc)


def generate_approval_note(
    findings: list[str],
    title: str,
    source_document: str,
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Build an approval note as .docx and return its path."""
    if not findings:
        raise DocumentGenerationError(
            "An approval note needs at least one finding to approve."
        )

    document = Document()
    document.core_properties.author = "Drishti Workbench"
    document.core_properties.title = title

    heading = document.add_paragraph()
    run = heading.add_run(title)
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = INK

    meta = document.add_paragraph()
    meta.add_run(f"Date: {date.today():%d %B %Y}\n").font.size = Pt(10)
    meta.add_run(f"Source document: {source_document}\n").font.size = Pt(10)
    meta.add_run("Prepared by: Drishti Workbench (on-premise)").font.size = Pt(10)

    document.add_paragraph()
    document.add_heading("Findings", level=1)
    for finding in findings:
        text = _as_text(finding)
        if text:
            document.add_paragraph(text, style="List Number")

    document.add_paragraph()
    document.add_heading("Approval", level=1)
    document.add_paragraph(
        "The findings above have been reviewed and are approved for action."
    )

    # A signature block a human actually signs. Tab stops rather than repeated
    # underscores, so the rules stay straight when the font changes.
    for label in ("Approved by", "Signature", "Date"):
        line = document.add_paragraph()
        line.paragraph_format.space_after = Pt(18)
        run = line.add_run(f"{label}: ")
        run.font.size = Pt(11)
        run = line.add_run("_" * 44)
        run.font.size = Pt(11)

    footer = document.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note = footer.add_run(
        "Generated offline by Drishti Workbench. Review before use."
    )
    note.font.size = Pt(8)
    note.italic = True

    path = _destination(title, ".docx", "approval-note")
    document.save(path)
    _record("approval_note", path, len(findings), user_id, thread_id)
    return str(path)


def generate_summary_deck(
    title: str,
    sections: list[dict[str, Any]],
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Build a summary deck as .pptx and return its path."""
    if not sections:
        raise DocumentGenerationError("A deck needs at least one section.")

    presentation = Presentation()
    presentation.core_properties.author = "Drishti Workbench"
    presentation.core_properties.title = title

    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = title
    if len(title_slide.placeholders) > 1:
        title_slide.placeholders[1].text = (
            f"Drishti Workbench · {date.today():%d %B %Y}"
        )

    bullet_count = 0
    for section in sections:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = str(
            section.get("heading") or section.get("title") or "Section"
        )

        bullets = section.get("bullets") or section.get("points") or []
        if isinstance(bullets, str):
            bullets = [bullets]

        body = slide.placeholders[1].text_frame
        body.clear()
        for index, bullet in enumerate(bullets):
            # text_frame always starts with one empty paragraph; reuse it
            # rather than leaving a blank bullet above the first real one.
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.text = _as_text(bullet)
            paragraph.level = 0
            paragraph.font.size = PptPt(18)
            bullet_count += 1

    path = _destination(title, ".pptx", "summary-deck")
    presentation.save(path)
    _record("summary_deck", path, len(sections), user_id, thread_id)
    return str(path)


def generate_calculation_sheet(
    title: str,
    steps: list[dict[str, Any]],
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Build an auditable calculation sheet as .xlsx and return its path."""
    if not steps:
        raise DocumentGenerationError("A calculation sheet needs at least one step.")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Calculation"

    sheet["A1"] = title
    sheet["A1"].font = Font(bold=True, size=14, color="2B2725")
    sheet["A2"] = f"Generated {date.today():%d %B %Y} · Drishti Workbench (offline)"
    sheet["A2"].font = Font(size=9, italic=True, color="6F665E")

    headers = ["Step", "Description", "Formula / Input", "Result"]
    header_row = 4
    fill = PatternFill("solid", fgColor=ACCENT_HEX)
    thin = Side(style="thin", color="E2DCCF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=header_row, column=column, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.border = border
        cell.alignment = Alignment(vertical="center")

    for offset, step in enumerate(steps, start=1):
        row = header_row + offset
        # Accept several key spellings: the values come from a model, and
        # rejecting a row because it said "input" instead of "formula" would
        # lose an audit step over a synonym.
        if not isinstance(step, dict):
            # A bare string step still deserves a row rather than being dropped.
            step = {"description": _as_text(step)}
        values = [
            step.get("step") or step.get("label") or offset,
            step.get("description") or step.get("desc") or "",
            step.get("formula") or step.get("input") or step.get("formula_input") or "",
            step.get("result") or step.get("value") or "",
        ]
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=column, value=_as_text(value))
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=column == 2)

    widths = [10, 52, 34, 22]
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width

    # Freeze below the header so the columns stay labelled when scrolling a
    # long derivation — the point of the sheet is that every step is visible.
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

    path = _destination(title, ".xlsx", "calculation-sheet")
    workbook.save(path)
    _record("calculation_sheet", path, len(steps), user_id, thread_id)
    return str(path)
