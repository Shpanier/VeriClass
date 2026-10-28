#!/usr/bin/env python3
"""Turn one Markdown file into an exercise package's exercise.yaml and
teacher.yaml: handy for a long step-by-step lab (a class-paced lab in a
Codespace, backend/pacing.py) whose text is mostly Markdown with code blocks.

    python scripts/steps_from_markdown.py <package folder>/source.md

writes exercise.yaml and teacher.yaml next to source.md (overwriting them).
Then check the folder with validate_exercise (MCP) or the dashboard.

The file:

    ---
    exercise_id: my-lab      # any exercise.yaml key
    title_en: ...
    pacing: class
    open_steps: 8
    ---

    # brief
    Markdown shown when the student opens the lab.

    # tutor_notes
    Instructions for the tutor model (optional).

    # steps

    ## A1 | Title of the step | 3            (label | title | minutes)
    The step's Markdown, code blocks and all.

    ~~~yaml teacher
    expected: what the teacher compares with
    expect_output:
      - match: '^ALL READY$'
        hint: ALL READY
    quiz:
      - q: A question asked after the step
        answer: The model answer
    ~~~

Headers inside ``` code blocks are ignored, so a Dockerfile comment stays code.
"""
import re
import sys
from pathlib import Path

import yaml


class _Literal(str):
    pass


def _literal(dumper, s):
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")


yaml.SafeDumper.add_representer(_Literal, _literal)


def _blocks(value):
    """Multi-line strings as | blocks, so the YAML stays readable."""
    if isinstance(value, str) and "\n" in value:
        return _Literal(value.rstrip("\n") + "\n")
    if isinstance(value, dict):
        return {k: _blocks(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_blocks(v) for v in value]
    return value


_STEP = re.compile(r"^## (.+?)\s*$")
_TEACHER = re.compile(r"^~~~\s*yaml\s+teacher\s*$")


def parse(text: str) -> tuple[dict, dict]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit("source.md must start with a --- front matter --- block")
    exercise = yaml.safe_load(m.group(1)) or {}
    sections: dict[str, list[str]] = {}
    steps: list[dict] = []
    teacher_steps: list[dict] = []
    current: list[str] | None = None
    teacher: list[str] | None = None
    in_code = False
    in_steps = False

    def close_step():
        if steps and isinstance(steps[-1]["text"], list):
            steps[-1]["text"] = "\n".join(steps[-1]["text"]).strip() + "\n"

    for line in text[m.end():].splitlines():
        if teacher is not None:
            if line.strip() == "~~~":
                teacher_steps[-1] = yaml.safe_load("\n".join(teacher)) or {}
                teacher = None
            else:
                teacher.append(line)
            continue
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code:
            if line.startswith("# ") and not line.startswith("## "):
                close_step()
                name = line[2:].strip()
                in_steps = name == "steps"
                current = None if in_steps else sections.setdefault(name, [])
                continue
            if in_steps and _STEP.match(line):
                close_step()
                parts = [p.strip() for p in _STEP.match(line).group(1).split("|")]
                step = {"label": parts[0], "title": parts[1], "text": []}
                if len(parts) > 2 and parts[2]:
                    step["minutes"] = float(parts[2]) if "." in parts[2] else int(parts[2])
                steps.append(step)
                teacher_steps.append({})
                current = step["text"]
                continue
            if in_steps and _TEACHER.match(line):
                teacher = []
                continue
        if current is not None:
            current.append(line)
    close_step()
    if in_code:
        raise SystemExit("a ``` code block is never closed")

    for name, lines in sections.items():
        exercise[name if name != "brief" else "brief_md"] = "\n".join(lines).strip() + "\n"
    exercise["steps"] = steps
    return exercise, {"steps": teacher_steps}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1])
    exercise, teacher = parse(source.read_text(encoding="utf-8"))
    dump = dict(allow_unicode=True, sort_keys=False, width=10_000, Dumper=yaml.SafeDumper)
    (source.parent / "exercise.yaml").write_text(yaml.dump(_blocks(exercise), **dump), encoding="utf-8")
    (source.parent / "teacher.yaml").write_text(yaml.dump(_blocks(teacher), **dump), encoding="utf-8")
    checked = sum(1 for s in teacher["steps"] if s.get("expect_output"))
    quiz = sum(len(s.get("quiz") or []) for s in teacher["steps"])
    print(f"{len(exercise['steps'])} steps, {checked} with an output check, {quiz} quiz questions "
          f"-> {source.parent}/exercise.yaml, teacher.yaml")


if __name__ == "__main__":
    main()
