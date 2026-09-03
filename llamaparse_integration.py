"""
llamaparse_integration.py
================================================================================
TanSathi - ITR Assistance
LlamaParse Integration -- Sprint 1 (10-08-2026 to 30-08-2026)

SCOPE (deliberately limited to this sprint):
    This module ONLY sends Form 16 / Form 26AS PDFs to LlamaParse and
    retrieves the parsed output (text, markdown, structured items). It does
    NOT extract tax fields, does NOT reconcile Form16 vs Form26AS, does NOT
    generate or validate any ITR data, and does NOT touch the Form16Schema /
    Form26ASSchema Pydantic models. Those belong to the next sprint
    (Document Parsing, 31-08-2026 to 13-10-2026) and beyond.

WHY `llama-cloud` and not `llama-cloud-services`:
    LlamaIndex announced new `llama-cloud` SDKs (Parse API v2) in Jan 2026.
    The older `llama-cloud-services` package (API v1) is in its deprecation
    window -- PyPI lists it as maintained only until 1 May 2026, which has
    already passed as of this sprint. New integrations should be built on
    `llama-cloud`, not the older package, even though plenty of older
    tutorials online still show `llama-cloud-services` / `from llama_parse
    import LlamaParse`. Every import/method/attribute used below was checked
    against the actually-installed `llama-cloud` package (v2.15.0) and the
    current official "Getting Started" docs -- not assumed from memory.
================================================================================
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llama_cloud import LlamaCloud

# Loads variables from a local .env file (if one exists) into the process
# environment for local development. In production/Docker/CI, set the real
# environment variable directly and this becomes a harmless no-op.
load_dotenv()

SUPPORTED_EXTENSIONS = {".pdf"}
DEFAULT_TIER = "agentic"  # good default for visually structured docs like Form16/26AS (tables, boxes)
DEFAULT_VERSION = "latest"


class LlamaParseConfigError(RuntimeError):
    """Raised when the API key or another required setting is missing/invalid."""


class LlamaParseJobError(RuntimeError):
    """Raised when a parse job fails, is cancelled, times out, or the upload fails."""


@dataclass
class ParsedDocument:
    """A thin, project-friendly wrapper around LlamaParse's raw result object."""
    source_path: Path
    job_id: str
    status: str
    page_count: int
    markdown_full: str
    text_full: str
    raw_result: object  # original llama_cloud ParsingGetResponse -- kept for advanced inspection (tables, images)


def get_client() -> LlamaCloud:
    """
    Build an authenticated LlamaCloud client.

    SECURITY: the API key is NEVER hard-coded here. It is read from the
    LLAMA_CLOUD_API_KEY environment variable -- loaded from a local .env
    file during development (see .env.example), or set directly in the real
    environment in production/Docker/CI.
    """
    api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise LlamaParseConfigError(
            "LLAMA_CLOUD_API_KEY is not set. Copy .env.example to .env and fill in your "
            "real key (get one at https://cloud.llamaindex.ai), or export it in your "
            "shell/deployment environment. Never hard-code the key in source code."
        )
    return LlamaCloud(api_key=api_key)


def _validate_file(file_path: str | Path) -> Path:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{path.suffix}'. Expected one of: {SUPPORTED_EXTENSIONS}")
    if path.stat().st_size == 0:
        raise ValueError(f"File is empty: {path}")
    return path


def parse_document(
    file_path: str | Path,
    tier: str = DEFAULT_TIER,
    version: str = DEFAULT_VERSION,
    client: Optional[LlamaCloud] = None,
) -> ParsedDocument:
    """
    Send ONE PDF (Form 16 or Form 26AS) to LlamaParse and return its parsed
    output. Works identically for both document types on purpose -- telling
    Form16 apart from Form26AS content is Document Parsing (next sprint),
    not this one.
    """
    path = _validate_file(file_path)
    client = client or get_client()

    try:
        uploaded = client.files.create(file=str(path), purpose="parse")
    except Exception as exc:
        raise LlamaParseJobError(f"Upload to LlamaParse failed for {path.name}: {exc}") from exc

    try:
        result = client.parsing.parse(
            file_id=uploaded.id,
            tier=tier,
            version=version,
            expand=["text", "markdown", "items"],
        )
    except Exception as exc:
        raise LlamaParseJobError(f"Parse job failed for {path.name}: {exc}") from exc

    if result.job.status != "COMPLETED":
        raise LlamaParseJobError(
            f"Parse job for {path.name} ended with status '{result.job.status}': "
            f"{result.job.error_message or 'no error message provided'}"
        )

    page_count = len(result.markdown.pages) if result.markdown else 0

    return ParsedDocument(
        source_path=path,
        job_id=result.job.id,
        status=result.job.status,
        page_count=page_count,
        markdown_full=result.markdown_full or "",
        text_full=result.text_full or "",
        raw_result=result,
    )


def save_parsed_output(parsed: ParsedDocument, output_dir: str | Path) -> dict:
    """
    Save parsed output to disk for manual inspection:
      <output_dir>/<name>.md          -- full markdown (headings, tables)
      <output_dir>/<name>.txt         -- full plain text
      <output_dir>/<name>_items.json  -- structured items (tables etc.) for later sprints to build on
    Returns the dict of paths written.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = parsed.source_path.stem

    md_path = out_dir / f"{base}.md"
    txt_path = out_dir / f"{base}.txt"
    items_path = out_dir / f"{base}_items.json"

    md_path.write_text(parsed.markdown_full, encoding="utf-8")
    txt_path.write_text(parsed.text_full, encoding="utf-8")

    items = getattr(parsed.raw_result, "items", None)
    items_data = items.model_dump() if items else {}
    items_path.write_text(json.dumps(items_data, indent=2, default=str), encoding="utf-8")

    return {"markdown": str(md_path), "text": str(txt_path), "items": str(items_path)}


def _print_summary(label: str, parsed: ParsedDocument) -> None:
    print(f"\n{'=' * 70}\n{label}: {parsed.source_path.name}\n{'=' * 70}")
    print(f"Job ID:      {parsed.job_id}")
    print(f"Status:      {parsed.status}")
    print(f"Pages:       {parsed.page_count}")
    print(f"Text chars:  {len(parsed.text_full)}")
    print(f"MD chars:    {len(parsed.markdown_full)}")
    preview = parsed.markdown_full[:400].replace("\n", " ")
    print(f"Preview:     {preview}...")


if __name__ == "__main__":
    # Manual smoke test: run against one Form16 + one Form26AS PDF.
    # Usage: python llamaparse_integration.py path/to/form16.pdf path/to/form26as.pdf
    if len(sys.argv) < 2:
        print("Usage: python llamaparse_integration.py <form16.pdf> [form26as.pdf]")
        sys.exit(1)

    output_dir = "parsed_output"
    labels = ["Form 16", "Form 26AS"]
    for label, file_arg in zip(labels, sys.argv[1:3]):
        try:
            parsed = parse_document(file_arg)
            _print_summary(label, parsed)
            paths = save_parsed_output(parsed, output_dir)
            print(f"Saved: {paths}")
        except (LlamaParseConfigError, LlamaParseJobError, FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {label} ({file_arg}): {exc}")
