"""
Model-specific context loader — plugin system for Neo-AI.

Drop any .md file into config/model_contexts/ and it is auto-discovered.
Optional YAML front-matter controls which mode/model the file applies to:

    ---
    mode: openai
    models: [o1, o3, o4, gpt-5]
    priority: 10
    ---

    Context instructions go here...

Resolution rules
----------------
- ``default.md`` (no front-matter, or stem == "default") always loads first.
- Files whose ``mode`` matches the active mode score higher.
- Files whose ``models`` list contains a substring of the active model name
  score highest.
- All matching files are concatenated in order (default → mode → model-specific)
  so each layer can add or refine instructions without replacing earlier ones.
- When ``mode`` or ``models`` are omitted the file applies to all modes/models
  at a lower priority tier.
"""

import logging
import re
from pathlib import Path
from typing import Optional

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

_FRONT_MATTER_RE = re.compile(r"^\s*---[ \t]*\n(.*?)\n[ \t]*---[ \t]*\n", re.DOTALL)


class ModelContextLoader:
    """Discover and merge model-specific context plugins."""

    #: Directory that is scanned for .md plugin files.
    CONTEXT_DIR: Path = Path(__file__).parent.parent / "config" / "model_contexts"

    # ── Public API ────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, mode: str, model: str) -> str:
        """Return the combined context string for *mode* and *model*.

        Scans :attr:`CONTEXT_DIR`, scores every ``.md`` file, and concatenates
        all matching bodies ordered from least-specific to most-specific so
        that model-level overrides naturally appear last in the prompt.
        """
        if not cls.CONTEXT_DIR.is_dir():
            logging.debug(
                "model_contexts directory not found — no extra context loaded: %s",
                cls.CONTEXT_DIR,
            )
            return ""

        # (score, name_length, body)  — collected for sorting
        candidates: list[tuple[int, int, str]] = []

        for path in sorted(cls.CONTEXT_DIR.glob("*.md")):
            front_matter, body = cls._parse_file(path)
            score = cls._score(front_matter, mode, model, path.stem)
            if score is not None and body.strip():
                candidates.append((score, len(path.stem), body.strip()))

        if not candidates:
            return ""

        # Low score first (default → mode → model-specific)
        candidates.sort(key=lambda x: (x[0], x[1]))
        parts = [body for _, _, body in candidates]

        logging.debug(
            "ModelContextLoader: loaded %d context block(s) for mode=%s model=%s",
            len(parts), mode, model,
        )
        return "\n\n".join(parts)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @classmethod
    def _parse_file(cls, path: Path) -> tuple[dict, str]:
        """Return ``(front_matter_dict, body_text)`` for a plugin file."""
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            logging.warning("Could not read context plugin %s: %s", path, exc)
            return {}, ""

        front_matter: dict = {}
        body = raw

        match = _FRONT_MATTER_RE.match(raw)
        if match:
            fm_text = match.group(1)
            body = raw[match.end():]

            if _YAML_AVAILABLE:
                try:
                    parsed = _yaml.safe_load(fm_text)
                    if isinstance(parsed, dict):
                        front_matter = parsed
                except Exception as exc:  # noqa: BLE001
                    logging.warning(
                        "Invalid YAML front-matter in %s: %s", path, exc
                    )
            else:
                # Minimal key: value fallback when PyYAML is not installed
                for line in fm_text.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        front_matter[k.strip()] = v.strip()

        return front_matter, body.strip()

    @classmethod
    def _score(
        cls,
        front_matter: dict,
        mode: str,
        model: str,
        stem: str,
    ) -> Optional[int]:
        """Return a match score or ``None`` if the file does not apply.

        Score tiers:
          0  — default / no filters  (always included)
          1  — mode-only match
          2  — mode + model substring match
        """
        fm_mode: str = str(front_matter.get("mode", "")).strip()
        fm_models = front_matter.get("models", [])

        # Normalise to list
        if isinstance(fm_models, str):
            fm_models = [fm_models]
        elif not isinstance(fm_models, list):
            fm_models = list(fm_models)

        is_default = stem == "default" and not fm_mode and not fm_models
        if is_default:
            return 0

        # No front-matter at all → treat like default
        if not fm_mode and not fm_models:
            return 0

        # Mode filter present but doesn't match → skip
        if fm_mode and fm_mode != mode:
            return None

        model_lower = model.lower()

        if fm_models:
            # At least one models entry must be a substring of the active model
            if any(str(m).lower() in model_lower for m in fm_models):
                return 2
            # Mode matched but model didn't → skip (don't fall back silently)
            if fm_mode:
                return None

        # Mode matched, no model filter
        if fm_mode == mode:
            return 1

        return None
