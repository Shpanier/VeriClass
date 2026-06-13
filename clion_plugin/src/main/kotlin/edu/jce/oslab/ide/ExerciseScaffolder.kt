package edu.jce.oslab.ide

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.guessProjectDir
import com.intellij.openapi.vfs.VfsUtil
import edu.jce.oslab.api.Exercise
import edu.jce.oslab.util.Format

/**
 * IDE-native mode only: drop a starter C file for the student's assigned
 * variant into the open project and open it in the editor. Never overwrites an
 * existing file (so a student's work is safe across restarts).
 */
object ExerciseScaffolder {

    fun scaffold(project: Project, filename: String, exercise: Exercise) {
        val baseDir = project.guessProjectDir() ?: return
        ApplicationManager.getApplication().invokeLater {
            if (project.isDisposed) return@invokeLater
            val existing = baseDir.findChild(filename)
            WriteCommandAction.runWriteCommandAction(project) {
                val file = existing ?: baseDir.createChildData(this, filename)
                if (existing == null) {
                    VfsUtil.saveText(file, template(exercise))
                }
                FileEditorManager.getInstance(project).openFile(file, true)
            }
        }
    }

    private fun template(exercise: Exercise): String {
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
}
