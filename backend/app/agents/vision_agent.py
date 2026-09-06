"""The vision specialist: scanned documents and photographs."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from app.agents.base_agent import Agent, AgentEvent, Delta
from app.core.config import settings
from app.core.logs import get_file_logger
from app.services import image_prep
from app.services.image_prep import ImagePrepError
from app.services.model_client import ModelServingClient, ModelServingError

log = get_file_logger("drishti.vision", "vision.log")

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"})
PDF_SUFFIXES = frozenset({".pdf"})

# llava:7b follows a simple sectioned format far more reliably than it follows
# a request for JSON, so the contract is plain text with two headed sections
# and the parsing is done here.
_EXTRACTION_PROMPT = """You are reading a scanned engineering inspection document from an oil refinery.

Reply in exactly this format, with both headings:

RAW TEXT:
<transcribe every line of text you can read on the page, preserving order>

FINDINGS:
- <one discrete observation, defect or measurement per line>
- <another>

Rules:
- A finding is a specific observation: a defect, a measurement, a condition, or a recommended action. Include the equipment tag and any numbers exactly as printed.
- Do not invent findings. If the page shows only three observations, list three.
- If the page is unreadable, write UNREADABLE under both headings."""


class VisionAgent(Agent):
    """Reads scanned pages and reports discrete findings.

    Holds no tools. Its capability is the preprocessing pipeline plus a vision
    model, not a set of functions it can call.
    """

    name: ClassVar[str] = "Vision Agent"
    allowed_tools: ClassVar[list[str]] = []
    instructions: ClassVar[str] = (
        "You read scanned engineering documents and report what is on the "
        "page. Never invent details that are not visible."
    )

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        super().__init__(client, model or settings.vision_model)

    async def extract_findings(self, image_or_pdf_path: str) -> dict[str, Any]:
        """Read a scan or PDF and return its text and discrete findings.

        Returns {"raw_text", "findings", "source_file"}. A PDF is rendered page
        by page and each page goes through the same pipeline, so a scan and a
        scanned PDF are treated identically from here on.
        """
        path = Path(image_or_pdf_path)
        suffix = path.suffix.lower()

        if suffix in PDF_SUFFIXES:
            pages = image_prep.pdf_pages_to_grayscale(path, settings.vision_max_pages)
        elif suffix in IMAGE_SUFFIXES:
            pages = [image_prep.load_grayscale(path)]
        else:
            raise ImagePrepError(
                f"Unsupported file type '{suffix}'. "
                f"Supported: {', '.join(sorted(IMAGE_SUFFIXES | PDF_SUFFIXES))}"
            )

        texts: list[str] = []
        findings: list[str] = []
        prep_notes: list[dict[str, Any]] = []

        for number, page in enumerate(pages, start=1):
            processed, notes = image_prep.preprocess(page)
            prep_notes.append(notes)

            message = self.client.image_message(
                _EXTRACTION_PROMPT,
                [(image_prep.to_png_bytes(processed), "image/png")],
            )
            reply = await self.client.chat_message(self.model, [message])
            content = (reply.get("content") or "").strip()

            page_text, page_findings = _parse_reply(content)
            if len(pages) > 1:
                texts.append(f"--- page {number} ---\n{page_text}")
                findings.extend(f"(p{number}) {f}" for f in page_findings)
            else:
                texts.append(page_text)
                findings.extend(page_findings)

        result = {
            "raw_text": "\n\n".join(t for t in texts if t).strip(),
            "findings": findings,
            "source_file": path.name,
        }

        # Metadata only — the extracted text belongs in the response, not in a
        # log file accumulating the contents of everything ever uploaded.
        log.info(
            "source=%s | pages=%d | findings=%d | raw_text_chars=%d | deskew=%s",
            path.name, len(pages), len(findings), len(result["raw_text"]),
            [n["deskew_degrees"] for n in prep_notes],
        )
        return result

    async def run_stream(
        self, message: str, context: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        """Handle a chat turn that carries an attachment."""
        path = context.get("attachment_path")
        if not path:
            yield Delta(
                "No file was attached. Drop an image or PDF onto the upload "
                "area and I will read it."
            )
            return

        try:
            result = await self.extract_findings(str(path))
            # Uploads are stored under a generated UUID name so a hostile
            # filename cannot become a path. Show the name the user
            # recognises, not the one on disk.
            display_name = context.get("attachment_name")
            if display_name:
                result = {**result, "source_file": str(display_name)}
        except ImagePrepError as exc:
            yield Delta(f"That file could not be read: {exc}")
            return
        except ModelServingError as exc:
            yield Delta(f"The vision model failed: {exc}")
            return

        for chunk in _format(result, message):
            yield Delta(chunk)


def _parse_reply(content: str) -> tuple[str, list[str]]:
    """Split the model's reply into transcription and findings.

    Falls back to treating the whole reply as the transcription and mining it
    for numbered or bulleted lines, because a weaker vision model sometimes
    ignores the format and simply transcribes.
    """
    if not content:
        return "", []

    # The LAST heading, not the first. The transcription reproduces the page,
    # and an inspection page has its own "FINDINGS" heading printed on it —
    # splitting on the first match cuts the transcription short and then mines
    # the transcribed items as though they were the model's analysis, which
    # yields every finding twice.
    headings = list(re.finditer(r"^\s*FINDINGS\s*:?\s*$", content, re.I | re.M))
    if headings:
        match = headings[-1]
        raw = content[: match.start()]
        tail = content[match.end() :]
    else:
        raw, tail = content, content

    raw = re.sub(r"^\s*RAW\s*TEXT\s*:?\s*$", "", raw, flags=re.I | re.M).strip()

    findings: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Bulleted or numbered lines only; prose between them is commentary.
        bullet = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)$", stripped)
        if bullet:
            text = bullet.group(1).strip()
            if text and text.upper() != "UNREADABLE":
                findings.append(text)

    # Deduplicate while preserving order: a page repeated across the raw-text
    # fallback would otherwise list every finding twice.
    seen: set[str] = set()
    unique = []
    for finding in findings:
        key = finding.lower()
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return raw, unique


def _format(result: dict[str, Any], question: str) -> list[str]:
    """Render the extraction for the chat stream."""
    findings = result["findings"]
    parts = [f"**Read `{result['source_file']}`**\n\n"]

    if findings:
        parts.append(f"**Findings ({len(findings)})**\n\n")
        parts.extend(f"{i}. {f}\n" for i, f in enumerate(findings, start=1))
    else:
        parts.append(
            "No discrete findings could be identified on this page.\n"
        )

    raw = result["raw_text"]
    if raw:
        excerpt = raw if len(raw) <= 1500 else raw[:1500] + "\n… (truncated)"
        parts.append(f"\n**Transcribed text**\n\n```\n{excerpt}\n```\n")

    if question.strip():
        parts.append(f"\n_You asked: {question.strip()}_\n")

    return parts
