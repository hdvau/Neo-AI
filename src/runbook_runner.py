"""
Runbook runner for Neo-AI.

Parses structured Markdown runbooks, executes every command block in order
(no approval prompts — runbooks are explicitly trusted by the user), collects
the output, and builds a prompt for the AI to analyse and report on.

Runbook format (Markdown):
  ## N. Section Title [OPTIONAL_TAG]
  ### N.M Subsection Title
  ```bash
  command --here
  ```
  **Analyze:**
  - threshold rules for the AI

Special sections (not executed, passed to AI as context):
  ## Agent Instructions
  ## Agent Output Format
  ## Baseline Reference
"""

import re
import subprocess
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RunbookSubsection:
    number: str
    title: str
    tags: list
    commands: list        # list of raw bash blocks (each block = one string)
    analyze: str
    section_title: str    # parent section title


@dataclass
class ParsedRunbook:
    title: str = ""
    agent_instructions: str = ""
    output_format: str = ""
    baseline: str = ""
    sections: list = field(default_factory=list)   # list[RunbookSubsection]


# ── Parser ────────────────────────────────────────────────────────────────────

class RunbookParser:
    _TAG_RE       = re.compile(r'`?\[([A-Z]+)\]`?')
    _CODE_RE      = re.compile(r'```(?:bash|sh)?\n(.*?)```', re.DOTALL)
    _ANALYZE_RE   = re.compile(r'\*\*Analyze:\*\*\s*(.*?)(?=\n#{1,3}\s|\Z)', re.DOTALL)
    _SECTION_RE   = re.compile(r'^## (\d+)\. (.+?)$', re.MULTILINE)
    _SUBSECTION_RE = re.compile(r'^### ([\d.]+)\s+(.+?)$', re.MULTILINE)

    def parse(self, content: str) -> ParsedRunbook:
        rb = ParsedRunbook()

        # Title
        m = re.search(r'^# (.+)', content, re.MULTILINE)
        if m:
            rb.title = m.group(1).strip()

        # Special prose sections
        rb.agent_instructions = self._extract_special(content, "Agent Instructions")
        rb.output_format      = self._extract_special(content, "Agent Output Format")
        rb.baseline           = self._extract_special(content, "Baseline Reference")

        # Numbered sections (## N. …)
        sec_positions = [(m.start(), m.group(1), m.group(2))
                         for m in self._SECTION_RE.finditer(content)]

        for idx, (sec_start, sec_num, sec_header) in enumerate(sec_positions):
            sec_end   = sec_positions[idx + 1][0] if idx + 1 < len(sec_positions) else len(content)
            sec_body  = content[sec_start:sec_end]
            sec_tags  = self._TAG_RE.findall(sec_header)
            sec_title = self._TAG_RE.sub('', sec_header).strip()

            # Subsections (### N.M …)
            sub_positions = [(m.start(), m.group(1), m.group(2))
                             for m in self._SUBSECTION_RE.finditer(sec_body)]

            for sidx, (sub_start, sub_num, sub_header) in enumerate(sub_positions):
                sub_end     = sub_positions[sidx + 1][0] if sidx + 1 < len(sub_positions) else len(sec_body)
                sub_body    = sec_body[sub_start:sub_end]
                sub_tags    = self._TAG_RE.findall(sub_header)
                sub_title   = self._TAG_RE.sub('', sub_header).strip()
                all_tags    = list(set(sec_tags + sub_tags))

                commands = [m.group(1).strip()
                            for m in self._CODE_RE.finditer(sub_body)
                            if m.group(1).strip()]

                analyze = ""
                am = self._ANALYZE_RE.search(sub_body)
                if am:
                    analyze = am.group(1).strip()

                if commands:   # skip subsections with no commands
                    rb.sections.append(RunbookSubsection(
                        number=sub_num.strip(),
                        title=sub_title,
                        tags=all_tags,
                        commands=commands,
                        analyze=analyze,
                        section_title=sec_title,
                    ))

        return rb

    def _extract_special(self, content: str, heading: str) -> str:
        """Extract body of a special ## heading (not numbered)."""
        pattern = re.compile(
            rf'^## {re.escape(heading)}.*?$\s*(.*?)(?=^## |\Z)',
            re.MULTILINE | re.DOTALL,
        )
        m = pattern.search(content)
        return m.group(1).strip() if m else ""


# ── Executor ──────────────────────────────────────────────────────────────────

class RunbookRunner:
    """Parse and execute a runbook; build AI analysis prompt."""

    #: Default runbooks search path (relative to project root).
    RUNBOOKS_DIR: Path = Path(__file__).parent.parent / "config" / "runbooks"

    def __init__(self, command_timeout: int = 60):
        self.command_timeout = command_timeout
        self._parser = RunbookParser()

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve_path(self, path_str: str) -> Path:
        """Resolve a runbook path: absolute, relative, or name inside RUNBOOKS_DIR."""
        p = Path(path_str)
        if p.is_absolute() and p.exists():
            return p
        if p.exists():
            return p.resolve()
        # Try name-only lookup in the runbooks directory
        candidates = [
            self.RUNBOOKS_DIR / path_str,
            self.RUNBOOKS_DIR / f"{path_str}.md",
        ]
        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError(
            f"Runbook '{path_str}' not found.\n"
            f"Checked: {p}, {self.RUNBOOKS_DIR / path_str}"
        )

    def run(
        self,
        path_str: str,
        tag_filter: Optional[str] = None,
        section_filter: Optional[str] = None,
        progress_cb=None,
    ) -> tuple:
        """Parse and execute a runbook.

        Args:
            path_str:       Path or name of the runbook file.
            tag_filter:     If set (e.g. "DAILY"), only run sections with that tag.
            section_filter: If set (e.g. "3"), only run sections whose number
                            starts with that string.
            progress_cb:    Optional callable(message: str) for real-time progress.

        Returns:
            (ParsedRunbook, collected_output_str)
        """
        path = self.resolve_path(path_str)
        content = path.read_text(encoding="utf-8")
        runbook = self._parser.parse(content)

        sections = runbook.sections

        if tag_filter:
            tag_upper = tag_filter.upper()
            sections = [s for s in sections if tag_upper in [t.upper() for t in s.tags]]

        if section_filter:
            sections = [s for s in sections if s.number.startswith(section_filter)]

        output_parts = []
        total = len(sections)

        for i, sec in enumerate(sections, 1):
            header = f"{sec.number}  {sec.section_title} › {sec.title}"
            if progress_cb:
                progress_cb(f"[{i}/{total}] {header}")

            output_parts.append(f"\n{'━' * 60}")
            output_parts.append(f"SECTION {header}")
            output_parts.append('━' * 60)

            for cmd_block in sec.commands:
                # Show a short label (first non-comment line)
                label_line = next(
                    (l.strip() for l in cmd_block.splitlines()
                     if l.strip() and not l.strip().startswith('#')),
                    cmd_block[:60],
                )
                if progress_cb:
                    progress_cb(f"    $ {label_line[:80]}{'…' if len(label_line) > 80 else ''}")

                output_parts.append(f"\n$ {label_line}")
                out = self._exec_block(cmd_block)
                output_parts.append(out)

            if sec.analyze:
                output_parts.append(f"\n[Analysis criteria for {sec.number}]")
                output_parts.append(sec.analyze)

        return runbook, "\n".join(output_parts)

    def run_sectioned(
        self,
        path_str: str,
        tag_filter: Optional[str] = None,
        section_filter: Optional[str] = None,
        progress_cb=None,
        log_path: Optional[Path] = None,
    ) -> tuple:
        """Parse and execute a runbook, returning output grouped by major section.

        Args:
            log_path: If provided, the raw command output is written to this
                      file so the user can verify AI findings against reality.

        Returns:
            (ParsedRunbook, list[dict]) where each dict has:
                'title'  — major section title (e.g. "Disk Health")
                'output' — combined command output for that section
        """
        path = self.resolve_path(path_str)
        content = path.read_text(encoding="utf-8")
        runbook = self._parser.parse(content)

        sections = runbook.sections

        if tag_filter:
            tag_upper = tag_filter.upper()
            sections = [s for s in sections if tag_upper in [t.upper() for t in s.tags]]

        if section_filter:
            sections = [s for s in sections if s.number.startswith(section_filter)]

        # Group subsections by their parent section title, preserving order.
        from collections import OrderedDict
        groups: OrderedDict = OrderedDict()
        for sec in sections:
            groups.setdefault(sec.section_title, []).append(sec)

        total = len(sections)
        counter = 0
        result = []
        log_lines = [
            f"Runbook: {runbook.title}",
            f"Executed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
        ]

        for section_title, subsections in groups.items():
            output_parts = []
            log_lines.append(f"\n{'=' * 70}")
            log_lines.append(f"SECTION: {section_title}")
            log_lines.append('=' * 70)

            for sec in subsections:
                counter += 1
                header = f"{sec.number}  {section_title} › {sec.title}"
                if progress_cb:
                    progress_cb(f"[{counter}/{total}] {header}")

                output_parts.append(f"\n{'━' * 60}")
                output_parts.append(f"SECTION {header}")
                output_parts.append('━' * 60)
                log_lines.append(f"\n--- {header} ---")

                for cmd_block in sec.commands:
                    label_line = next(
                        (l.strip() for l in cmd_block.splitlines()
                         if l.strip() and not l.strip().startswith('#')),
                        cmd_block[:60],
                    )
                    if progress_cb:
                        progress_cb(f"    $ {label_line[:80]}{'…' if len(label_line) > 80 else ''}")

                    output_parts.append(f"\n$ {label_line}")
                    log_lines.append(f"\n$ {cmd_block.strip()}")
                    out = self._exec_block(cmd_block)
                    output_parts.append(out)
                    log_lines.append(out)

                if sec.analyze:
                    output_parts.append(f"\n[Analysis criteria for {sec.number}]")
                    output_parts.append(sec.analyze)

            result.append({
                'title':  section_title,
                'output': "\n".join(output_parts),
            })

        # Write raw output log if a path was provided.
        if log_path:
            try:
                log_path = Path(log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("\n".join(log_lines), encoding="utf-8")
            except OSError as e:
                logging.warning("Could not write runbook log to %s: %s", log_path, e)

        return runbook, result

    def build_ai_prompt(self, runbook: ParsedRunbook, output: str) -> str:
        """Build the full prompt to send to the AI for analysis."""
        parts = [
            "You are analysing the output of an automated server health-check runbook.",
            f"Runbook: {runbook.title}",
            f"Executed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        if runbook.agent_instructions:
            parts += ["## Your Instructions", runbook.agent_instructions, ""]

        if runbook.baseline:
            parts += ["## Baseline Reference (expected values for this server)",
                      runbook.baseline, ""]

        parts += [
            "## Command Output",
            "Each section shows the commands run and their exact output,",
            "followed by the analysis criteria defined in the runbook.",
            "",
            output,
            "",
        ]

        if runbook.output_format:
            parts += [
                "## Required Output Format",
                "Produce your report using exactly this structure:",
                "",
                runbook.output_format,
            ]

        return "\n".join(parts)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _exec_block(self, block: str) -> str:
        """Run a bash block (may be multi-line / contain loops) and return output."""
        try:
            result = subprocess.run(
                block,
                shell=True,
                executable="/bin/bash",
                capture_output=True,
                text=True,
                timeout=self.command_timeout,
            )
            combined = result.stdout
            if result.stderr.strip():
                combined += result.stderr
            return combined.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[TIMEOUT after {self.command_timeout}s]"
        except Exception as exc:
            return f"[ERROR: {exc}]"

    # ── Discovery ─────────────────────────────────────────────────────────────

    @classmethod
    def list_runbooks(cls) -> list:
        """Return runbook names available in RUNBOOKS_DIR (for tab completion)."""
        if not cls.RUNBOOKS_DIR.is_dir():
            return []
        return sorted(p.stem for p in cls.RUNBOOKS_DIR.glob("*.md"))
