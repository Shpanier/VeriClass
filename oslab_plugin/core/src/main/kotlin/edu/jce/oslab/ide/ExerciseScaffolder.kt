package edu.jce.oslab.ide

import com.intellij.openapi.application.ApplicationInfo
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.guessProjectDir
import com.intellij.openapi.vfs.VfsUtil
import edu.jce.oslab.api.Exercise
import edu.jce.oslab.util.Format

/**
 * IDE-native mode only: drop a starter file for the student's assigned variant
 * into the open project and open it in the editor. Never overwrites an existing
 * file (so a student's work is safe across restarts).
 *
 * The starter language follows the backend-chosen [scaffold filename][filename]:
 * a `.py` name yields a Python starter (PyCharm cohorts), a `.c`/`.cpp` name a
 * C starter (CLion cohorts). When the extension is missing or unrecognized we
 * fall back to the running IDE — PyCharm ⇒ Python, everything else ⇒ C — so the
 * single shared `core` serves both plugins without a build-time switch.
 */
object ExerciseScaffolder {

    private enum class Lang { C, PYTHON }

    fun scaffold(project: Project, filename: String, exercise: Exercise) {
        val baseDir = project.guessProjectDir() ?: return
        ApplicationManager.getApplication().invokeLater {
            if (project.isDisposed) return@invokeLater
            val existing = baseDir.findChild(filename)
            WriteCommandAction.runWriteCommandAction(project) {
                val file = existing ?: baseDir.createChildData(this, filename)
                if (existing == null) {
                    VfsUtil.saveText(file, template(exercise, langFor(filename)))
                }
                FileEditorManager.getInstance(project).openFile(file, true)
            }
        }
    }

    private fun langFor(filename: String): Lang =
        when (filename.substringAfterLast('.', "").lowercase()) {
            "py" -> Lang.PYTHON
            "c", "cpp", "cc", "cxx", "h", "hpp" -> Lang.C
            else -> if (isPyCharm()) Lang.PYTHON else Lang.C   // ambiguous name → follow the IDE
        }

    /** Product code is "PC"/"PY" on PyCharm, "CL" on CLion, "IC"/"IU" on IDEA. */
    private fun isPyCharm(): Boolean =
        ApplicationInfo.getInstance().build.productCode.let { it == "PC" || it == "PY" }

    private fun template(exercise: Exercise, lang: Lang): String =
        when (lang) {
            Lang.C -> cTemplate(exercise)
            Lang.PYTHON -> pythonTemplate(exercise)
        }

    private fun cTemplate(exercise: Exercise): String {
        val v = exercise.variant
        val sb = StringBuilder()
        sb.append("/*\n")
        sb.append(" * ").append(exercise.title_en).append("\n")
        if (v != null) {
            sb.append(" * Your variant: ").append(v.id).append("\n")
            sb.append(" *\n")
            sb.append(" * Parameters:\n")
            for ((k, value) in v.params) {
                sb.append(" *   ").append(k).append(" = ").append(Format.value(value)).append("\n")
            }
            sb.append(" *\n")
            sb.append(" * Test inputs you must pass:\n")
            for (t in v.test_inputs) {
                sb.append(" *   mcalc \"").append(t.input).append("\"  ->  ")
                    .append(t.expected_output).append("\n")
            }
        }
        sb.append(" *\n")
        sb.append(" * The OS Lab tutor (right-hand tool window) can help — but it will not\n")
        sb.append(" * hand you a finished solution.\n")
        sb.append(" */\n\n")
        sb.append("#include <stdio.h>\n")
        sb.append("#include <stdlib.h>\n")
        sb.append("#include <string.h>\n\n")
        sb.append("/* TODO: parse the expression, respect operator precedence, and print the\n")
        sb.append("   integer result (or the exact required error string) to stdout. */\n")
        sb.append("int mcalc(const char *expr) {\n")
        sb.append("    (void)expr;\n")
        sb.append("    /* your code here */\n")
        sb.append("    return 0;\n")
        sb.append("}\n\n")
        sb.append("int main(int argc, char **argv) {\n")
        sb.append("    if (argc < 2) {\n")
        sb.append("        fprintf(stderr, \"usage: %s \\\"<expression>\\\"\\n\", argv[0]);\n")
        sb.append("        return 1;\n")
        sb.append("    }\n")
        sb.append("    return mcalc(argv[1]);\n")
        sb.append("}\n")
        return sb.toString()
    }

    private fun pythonTemplate(exercise: Exercise): String {
        val v = exercise.variant
        val sb = StringBuilder()
        sb.append("\"\"\"\n")
        sb.append(exercise.title_en).append("\n")
        if (v != null) {
            sb.append("Your variant: ").append(v.id).append("\n\n")
            sb.append("Parameters:\n")
            for ((k, value) in v.params) {
                sb.append("  ").append(k).append(" = ").append(Format.value(value)).append("\n")
            }
            sb.append("\nTest inputs you must pass:\n")
            for (t in v.test_inputs) {
                sb.append("  \"").append(t.input).append("\"  ->  ")
                    .append(t.expected_output).append("\n")
            }
        }
        sb.append("\n")
        sb.append("How it is run and graded: your program is fed one line on standard input\n")
        sb.append("like  prog \"<input>\"  and must print the answer as its LAST line. The\n")
        sb.append("skeleton below reads that line and hands you the quoted text as `arg`.\n\n")
        sb.append("The OS Lab tutor (right-hand tool window) can help — but it will not\n")
        sb.append("hand you a finished solution.\n")
        sb.append("\"\"\"\n\n")
        sb.append("import re\n")
        sb.append("import sys\n\n\n")
        sb.append("def solve(arg: str) -> str:\n")
        sb.append("    \"\"\"Compute the answer for `arg` and return it as a string\n")
        sb.append("    (or the exact required error string).\"\"\"\n")
        sb.append("    # TODO: your code here\n")
        sb.append("    raise NotImplementedError\n\n\n")
        sb.append("if __name__ == \"__main__\":\n")
        sb.append("    line = sys.stdin.readline()\n")
        sb.append("    m = re.search(r'\"(.*)\"', line)          # the text between the quotes\n")
        sb.append("    arg = m.group(1) if m else line.strip()\n")
        sb.append("    print(solve(arg))\n")
        return sb.toString()
    }
}
