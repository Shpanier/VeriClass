# Writing exercises

An exercise is a **package**: a folder of text files. Copy
[`first-lab/`](first-lab), change it, zip the folder, and drop the zip on the
dashboard's **Exercises** tab. The upload is checked before anything is
installed: errors say what to fix, notes point at likely mistakes. Upload a
package with the same `exercise_id` again to update it (the dashboard asks
first; the previous version is kept in a backup folder).

Then offer the exercise in a course (*Courses & students → the course → tick
it*). Students see only the exercises their course offers.

```
first-lab/
  exercise.yaml   what students and the tutor see
  teacher.yaml    only for you: never sent to students or to the tutor
  faq.yaml        optional: the question bank
  files/          optional: what students download from the chat
  solution/       optional: your solution; never served
  source.md       optional: where the lab came from; never served
```

Zipping: on macOS right-click the folder → *Compress*; on Windows right-click →
*Send to → Compressed (zipped) folder*. The zip may hold the folder itself or
its contents.

Installed packages live in `data/exercises/<exercise_id>/` in the VeriClass
folder. You can also edit those files directly and press *Reload from disk* on
the Exercises tab, and *Export* gives any exercise back as a zip.

## exercise.yaml

```yaml
exercise_id: first-lab              # a short id; letters, digits and dashes
title_en: "Your first lab: Python warm-up"
title_he: "מעבדה ראשונה: חימום בפייתון"    # optional
language: python                    # optional: python, c, bash, …
default_mode: mentor                # mentor (guides with questions) | coding_partner (more direct)

brief_md: |                         # Markdown, shown when a student opens the exercise
  **Welcome!** Three short steps…

welcome_suggestions:                # optional: buttons under the brief
  - "I'm stuck. A hint, please?"

tutor_notes: |                      # optional: instructions for the tutor; students never see them
  Never write the program for them…

steps:                              # optional: a step-by-step lab
  - label: A1                       # optional: the step's name in the chat and the dashboard
    title: "Check Python"
    minutes: 3
    text: |                         # Markdown; put commands in ```bash blocks
      Run `python3 --version`…
```

The chat speaks the lab's language: Hebrew when the brief (or the first step's
title) is in Hebrew, otherwise English. The lecturer can fix it to one language
in *Settings*.

### A class-paced lab

Add these to run the lab with the whole class on the same step (see the
[lecturer's guide](../docs/GUIDE.md#class-paced-labs)):

```yaml
pacing: class          # you open the steps for the whole class, from the dashboard
open_steps: 1          # steps 1..N are open from the start (each student at their own pace)
```

| Setting | What it does | Default |
|---|---|---|
| `quiz_review: partial \| zero \| off` | A quiz answer that waits for you before the next step: graded below 2/2, only 0/2, or never | `partial` |
| `output_in_chat: confirm \| accept \| ask \| off` | A chat message while a step is open: is it the step's output? | `confirm` |
| `answer_in_chat: detect \| confirm \| answer` | A chat message while a question is open: is it the answer? | `detect` |
| `chat_history: false` | Don't replay the conversation after a new sign-in | on |
| `resume_minutes: N` | How recent a session must be to be resumed; `0` = always | always for class-paced labs |

### Versions per student

A coding exercise can give each student a different version, so a neighbour's
answer doesn't fit. Each version has parameters (shown in the student's brief
and usable in the text as `@name`) and test inputs:

```yaml
variants:
  - id: A
    params: { N: 5, operator: "+" }
    test_inputs:
      - { input: "1+1", expected_output: "2" }
  - id: B
    params: { N: 7, operator: "*" }
    test_inputs:
      - { input: "2*3", expected_output: "6" }
```

Each student always gets the same version. Without `variants`, everyone gets
the same exercise. The three samples that ship with VeriClass
(`config/exercises/`) use versions.

## teacher.yaml

Per step, in the same order as the steps in exercise.yaml:

```yaml
notes: |                            # optional: your notes about the whole lab
  Students who finish early can…

steps:
  - expected: Python 3 is installed.          # the answer in words, shown to you
    expected_output: |                        # what the commands print, shown to you
      Python 3.12.6                           # next to a student's pasted output
    expect_output:                            # checks a pasted output must pass
      - match: '^Python 3\.\d+'               # a regular expression, tried line by line
        hint: the "Python 3.x" line           # what you see when it's missing
    quiz:                                     # questions after the step
      - q: What does the program you just ran do?
        answer: It prints the text to the screen.   # the model answer for grading
        always: true                          # asked without your approval
      - q: Why does range(1, 6) stop at 5?
        answer: range stops before its end value.   # asked once you approve it
```

A pasted output that passes every check moves the student on by itself; one
that doesn't waits for you (*Let them continue* or *Send back*). Students never
see the expected output, the checks or the model answers.

## faq.yaml: the question bank

Questions students are likely to ask, with ready answers at up to four levels.
In review mode the matching answer is shown first, and every answer you send
can be saved into the bank, so it grows as you teach.

```yaml
questions:
  - id: q01
    step: 1                                  # optional: the step it belongs to
    question: "python3 is not found. What do I do?"
    paraphrases: ["command not found: python3"]
    answers:
      nudge:  { en: "Which operating system are you on?", he: "באיזו מערכת הפעלה אתם עובדים?" }
      normal: { en: "On Windows try `python --version`…",  he: "ב־Windows נסו `python --version`…" }
      # also: more (more detail), direct (the plain answer)
```

About 50 questions cover most of what a class asks.

## Other ways to write a package

- **From one Markdown file.** A long lab is easier to write as a single
  Markdown file: `uv run python scripts/steps_from_markdown.py <folder>/source.md`
  writes exercise.yaml and teacher.yaml from it (the format is at the top of
  the script).
- **With a coding agent.** The MCP server in `vericlass_mcp/` gives Claude Code
  (or another MCP client) tools for your own VeriClass: start a package, check
  it, install it, import students, read an anonymized class report. See
  [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md#writing-exercises-with-a-coding-agent).
- **In the dashboard.** *Exercises → New exercise* writes a simple exercise
  (brief, steps, expected answers, tutor notes) without files; class pacing,
  quiz questions, the question bank and files come only from a package.
