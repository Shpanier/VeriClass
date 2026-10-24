package edu.jce.vericlass.terminal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class CommandCheckerTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val policy = TerminalPolicy(
        allow = setOf(
            "ls", "cat", "grep", "awk", "sort", "uniq", "head", "tail", "wc", "cut", "tr",
            "xargs", "env", "find", "git", "chmod", "mkdir", "sed", "timeout",
        ),
        scripts = true,
    )

    private fun ok(line: String, p: TerminalPolicy = policy, cwd: File? = null) {
        val v = CommandChecker.check(line, p, cwd)
        assertTrue("expected allowed: $line — got ${v.reason}", v.allowed)
    }

    private fun no(line: String, p: TerminalPolicy = policy, cwd: File? = null): CommandVerdict {
        val v = CommandChecker.check(line, p, cwd)
        assertFalse("expected refused: $line", v.allowed)
        return v
    }

    @Test
    fun `plain allowed commands and builtins`() {
        ok("ls -la")
        ok("cd logs")
        ok("echo hello; pwd")
        ok("export X=1")
        ok("X=1 grep foo file.txt")
        ok("")
        ok("   # just a comment")
    }

    @Test
    fun `pipelines and lists check every program`() {
        ok("awk '\$9==500 {print \$1}' access.log | sort | uniq -c | sort -rn | head -1")
        ok("grep -c 404 access.log && echo found || echo none")
        ok("tail -n 100 access.log | awk '{print \$9}' | sort | uniq -c")
        no("cat access.log | sh")
        no("echo hi && powershell")
        no("ls; python3 -c 'print(1)'")
        no("ls|bash")
        no("ls &bash")
    }

    @Test
    fun `redirections are not commands`() {
        ok("grep 500 access.log > errors.txt 2>&1")
        ok("sort < in.txt >> out.txt")
        ok("cat access.log 2>/dev/null | wc -l")
        ok("ls &> all.txt")
        ok("echo a>b")
    }

    @Test
    fun `substitutions are checked`() {
        ok("echo \"there are \$(wc -l < access.log) lines\"")
        ok("echo `ls | wc -l`")
        ok("X=\$(grep -c 404 access.log)")
        no("echo \"\$(bash)\"")
        no("echo `sh -c id`")
        no("X=\$(python3 x.py)")
        no("diff <(ls) <(python3 x.py)")
        no("echo \${X:-\$(bash)}")
        no("echo \$(( \$(python3 -c 1) + 1 ))")
        ok("echo \$(( 1 + 2 ))")
    }

    @Test
    fun `compound commands check their bodies`() {
        ok("for f in *.log; do wc -l \$f; done")
        ok("if grep -q 500 access.log; then echo yes; else echo no; fi")
        ok("while read l; do echo \$l; done < access.log")
        ok("{ ls; pwd; }")
        ok("(cd logs && ls)")
        no("for f in *.log; do python3 \$f; done")
        no("if true; then bash; fi")
        no("(cd logs; sh)")
    }

    @Test
    fun `names computed at run time are refused`() {
        no("\$X")
        no("X=powersh; \${X}ell")
        no("/bin/ba*")
        no("\"\$SHELL\" -c id")
    }

    @Test
    fun `quoting can't hide a name`() {
        no("'ba'sh")
        no("b\\ash")
        no("\"python3\" x.py")
    }

    @Test
    fun `paths, exe suffixes and case are normalized`() {
        no("/bin/bash")
        no("/usr/bin/python3 x.py")
        no("CMD.EXE /c dir")
        no("PowerShell")
        ok("/bin/ls -la")
        assertEquals("python3", CommandChecker.normalize("C:\\Python\\Python3.EXE"))
    }

    @Test
    fun `shells and eval-like builtins`() {
        no("sh")
        no("bash -c 'ls'")
        no("eval ls")
        no("exec ls")
        no("source")
        val v = no("zsh")
        assertTrue(v.reason!!.contains("another shell"))
    }

    @Test
    fun `wrappers check the program they start`() {
        ok("find . -name '*.log' | xargs wc -l")
        ok("xargs -n 1 echo")
        ok("env FOO=1 grep x f")
        ok("timeout 5 tail -f access.log")
        ok("find . -name '*.log' -exec wc -l {} \\;")
        no("find . -exec sh -c 'id' \\;")
        no("echo x | xargs python3")
        no("env FOO=1 bash")
        no("timeout 5 bash")
        ok("command -v bash")
        no("command bash")
    }

    @Test
    fun `awk and git escape hatches`() {
        ok("awk '{ if (\$9 == 500 || \$9 == 404) print \$1 }' access.log")
        ok("awk '{ printf \"%s|%s\\n\", \$1, \$2 }' access.log")
        no("awk 'BEGIN { system(\"sh\") }'")
        no("awk 'BEGIN { \"date\" | getline d; print d }'")
        no("awk '{ print | \"sh\" }'")
        ok("git status")
        ok("git commit -m 'fix: count 404s'")
        ok("git config user.name 'Dana'")
        no("git -c core.pager=sh log")
        no("git config alias.x '!sh'")
    }

    @Test
    fun `not in the allow list`() {
        val v = no("curl http://example.com")
        assertEquals("'curl' isn't allowed in this exercise", v.reason)
        assertEquals(listOf("curl"), v.commands)
    }

    @Test
    fun `syntax errors are not violations`() {
        val v = no("echo 'unclosed")
        assertTrue(v.syntaxError)
        assertTrue(v.reason!!.startsWith("syntax error"))
        assertFalse(no("bash").syntaxError)
    }

    @Test
    fun `scripts are scanned with the same rules`() {
        val dir = tmp.root
        File(dir, "good.sh").writeText("#!/bin/sh\n# count errors\ngrep -c 500 access.log | wc -l\n")
        File(dir, "bad.sh").writeText("#!/bin/sh\nls\npython3 -c 'import os'\n")
        File(dir, "heredoc.sh").writeText("cat <<EOF\npython3 is just text here\nEOF\nls\n")
        ok("./good.sh", cwd = dir)
        ok("sh good.sh", cwd = dir)
        ok(". good.sh", cwd = dir)
        ok("./heredoc.sh", cwd = dir)
        val v = no("./bad.sh", cwd = dir)
        assertTrue(v.reason!!.contains("python3"))
        no("bash bad.sh", cwd = dir)
        no("./good.sh", p = policy.copy(scripts = false), cwd = dir)
        // A typo'd path the shell will just call "not found" isn't a violation.
        ok("./logq.hs", cwd = dir)
    }

    @Test
    fun `commands are listed for the log`() {
        val v = CommandChecker.check("grep 404 a.log | sort | uniq -c", policy)
        assertEquals(listOf("grep", "sort", "uniq"), v.commands)
    }
}
