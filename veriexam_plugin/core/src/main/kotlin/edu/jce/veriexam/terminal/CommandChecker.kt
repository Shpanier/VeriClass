package edu.jce.veriexam.terminal

import java.io.File

/** What the active exercise lets the student run in the VeriExam terminal. */
data class TerminalPolicy(
    /** Program names the student may run (lowercase, no path, no `.exe`). */
    val allow: Set<String>,
    /** Allow `./script.sh`, `sh script.sh` and `. script.sh` — after scanning the script with the same rules. */
    val scripts: Boolean = true,
    /** The exercise's note shown under every refused line: where to run the command instead. */
    val blockedHint: String? = null,
)

/** The checker's answer for one command line. */
data class CommandVerdict(
    val allowed: Boolean,
    /** Every program name found in the line, in order — logged for the teacher either way. */
    val commands: List<String>,
    /** Why the line was refused, phrased for the student. Null when allowed. */
    val reason: String? = null,
    /**
     * The line was refused because it doesn't parse (an unclosed quote or paren),
     * not because of the policy. Not run — our parse and the shell's could differ —
     * but not a violation either, so it isn't reported as one.
     */
    val syntaxError: Boolean = false,
)

/**
 * Decides whether one command line may run. It parses the line the way a POSIX
 * shell would split it — quotes, escapes, pipes, `&&`/`||`/`;`, redirections,
 * `$(…)`/backticks, subshells, `if`/`while`/`for` bodies — and checks EVERY
 * program it would start, not just the first word. So `cat x | sh`,
 * `echo hi && powershell` and `echo "$(bash)"` are all caught.
 *
 * This is detect-and-report, not a sandbox: a determined student can still hide
 * a program behind tricks the parser can't see through (a program that itself
 * starts programs, for instance). Anything whose program name is computed at run
 * time — `$X`, `${X}ell`, `/bin/ba*` — is refused outright, and every line
 * typed is logged regardless, so the teacher still sees the attempt.
 */
object CommandChecker {

    /** Shell builtins that don't start another program. Always allowed. */
    private val SAFE_BUILTINS = setOf(
        "cd", "pwd", "echo", "printf", "export", "unset", "true", "false", "test", "[",
        "read", "set", "shift", "exit", "type", "which", "wait", "umask", "history",
        "clear", "help", ":", "let", "local", "return", "break", "continue", "getopts", "[[", "]]",
    )

    /** Builtins that run arbitrary shell code. Never allowed, whatever the exercise says. */
    private val ALWAYS_BLOCKED = setOf("eval", "exec", "trap", "builtin", "enable", "alias", "coproc", "fc")

    /** Programs that are a shell themselves. Only allowed as `sh script.sh` when scripts are on. */
    private val SHELLS = setOf(
        "sh", "bash", "ash", "dash", "zsh", "ksh", "mksh", "fish", "csh", "tcsh",
        "powershell", "pwsh", "cmd", "wsl", "wsl.exe",
    )
    private val SCRIPT_SHELLS = setOf("sh", "bash", "ash", "dash", "zsh", "ksh", "mksh")

    /** Reserved words after which the next word is a command. */
    private val LEADING_KEYWORDS = setOf("if", "then", "else", "elif", "do", "while", "until", "!", "{", "time")

    /** Reserved words that close a block; a segment holding only one of them runs nothing. */
    private val CLOSING_KEYWORDS = setOf("fi", "done", "}", "esac", "then", "else", "do")

    /** Segments that start with these are loop/case headers: their words aren't commands. */
    private val HEADER_KEYWORDS = setOf("for", "case", "select", "in")

    private const val MAX_SCRIPT_BYTES = 64 * 1024
    private const val MAX_DEPTH = 4

    fun check(line: String, policy: TerminalPolicy, cwd: File? = null): CommandVerdict {
        val ctx = Ctx(policy, cwd)
        checkText(line, ctx, depth = 0)
        return CommandVerdict(ctx.reason == null, ctx.commands, ctx.reason, ctx.syntax)
    }

    // --- the walk --------------------------------------------------------------

    private class Ctx(val policy: TerminalPolicy, val cwd: File?) {
        val commands = mutableListOf<String>()
        var reason: String? = null
        var syntax = false
        fun refuse(why: String) {
            if (reason == null) reason = why
        }
        fun syntaxError(why: String) {
            if (reason == null) {
                reason = "syntax error: $why"
                syntax = true
            }
        }
    }

    private fun checkText(text: String, ctx: Ctx, depth: Int) {
        if (depth > MAX_DEPTH) {
            ctx.refuse("this line nests too many commands inside each other")
            return
        }
        val scan = Scanner(text).also { it.run() }
        scan.problem?.let { if (depth == 0) ctx.syntaxError(it) else ctx.refuse("a script it runs has a $it") }
        for (segment in segments(scan.tokens)) checkSegment(segment, ctx, depth)
        for (sub in scan.substitutions) checkText(sub, ctx, depth + 1)
    }

    /** Split the token stream into simple commands at every control operator. */
    private fun segments(tokens: List<Tok>): List<List<Tok>> {
        val out = mutableListOf<List<Tok>>()
        var cur = mutableListOf<Tok>()
        for (t in tokens) {
            if (t is Tok.Op && t.op != "redir") {
                if (cur.isNotEmpty()) out += cur
                cur = mutableListOf()
            } else {
                cur += t
            }
        }
        if (cur.isNotEmpty()) out += cur
        return out
    }

    private fun checkSegment(segment: List<Tok>, ctx: Ctx, depth: Int) {
        // Drop redirections (`> out.txt`, `2>&1`, `< in`) and their targets.
        val words = mutableListOf<Tok.Word>()
        var skipNext = false
        for (t in segment) {
            when {
                t is Tok.Op -> skipNext = true // a redirection operator: the next word is its target
                skipNext -> skipNext = false
                else -> words += t as Tok.Word
            }
        }
        var i = 0
        // Leading `X=1 Y=2 cmd`: assignments aren't commands.
        while (i < words.size && words[i].isAssignment()) i++
        // `if cmd`, `while cmd`, `! cmd`, `{ cmd`, `time cmd`: the command comes next.
        while (i < words.size && !words[i].quoted && words[i].value in LEADING_KEYWORDS) i++
        while (i < words.size && words[i].isAssignment()) i++
        if (i >= words.size) return
        val first = words[i]
        if (!first.quoted && first.value in HEADER_KEYWORDS) return
        if (!first.quoted && first.value in CLOSING_KEYWORDS && i == words.size - 1) return
        checkCommand(first, words.subList(i + 1, words.size), ctx, depth)
    }

    private fun checkCommand(cmd: Tok.Word, args: List<Tok.Word>, ctx: Ctx, depth: Int) {
        if (cmd.dynamic || cmd.glob) {
            ctx.commands += cmd.raw
            ctx.refuse("the program name '${cmd.raw}' is built at run time, so it can't be checked")
            return
        }
        val word = cmd.value
        val name = normalize(word)
        ctx.commands += name
        val p = ctx.policy

        if (name in SAFE_BUILTINS) return
        if (name in ALWAYS_BLOCKED) {
            ctx.refuse("'$name' can run any command, so it's not allowed here")
            return
        }
        if (name == "command") {
            // `command -v ls` only looks a name up; `command ls` runs ls.
            if (args.none { it.value == "-v" || it.value == "-V" }) inner(args, ctx, depth)
            return
        }
        if (name == "source" || name == ".") {
            checkScriptRun(name, args.firstOrNull()?.value, ctx, depth)
            return
        }
        if (isPath(word)) {
            val file = resolve(word, ctx.cwd)
            if (file != null && file.isFile && looksLikeScript(file)) {
                checkScriptRun(word, word, ctx, depth)
                return
            }
            // Nothing there (a typo like ./logq.hs): the shell will just say "not found",
            // so don't count it as a violation. Windows also tries name.exe and friends.
            val exists = file == null || file.exists() || WINDOWS_EXTS.any { File(file.path + it).exists() }
            if (!exists) return
            // A compiled program run by path: judge it by its file name.
        }
        if (name in SHELLS) {
            val firstArg = args.firstOrNull()
            if (name in SCRIPT_SHELLS && firstArg != null && !firstArg.value.startsWith("-")) {
                checkScriptRun(name, firstArg.value, ctx, depth)
            } else {
                ctx.refuse("starting another shell ('$name') isn't allowed here")
            }
            return
        }
        if (name !in p.allow) {
            ctx.refuse("'$name' isn't allowed in this exercise")
            return
        }
        // Allowed — but some allowed programs start other programs. Check those too.
        when (name) {
            "env" -> inner(args, ctx, depth, skipAssignments = true, flagsWithValue = setOf("-u", "--unset", "-C", "--chdir", "-S"))
            "xargs" -> inner(
                args, ctx, depth,
                flagsWithValue = setOf("-n", "-L", "-P", "-s", "-I", "-d", "-E", "-e", "-a", "--max-args", "--max-procs", "--delimiter"),
            )
            "nice" -> inner(args, ctx, depth, flagsWithValue = setOf("-n", "--adjustment"))
            "nohup", "stdbuf" -> inner(args, ctx, depth, flagsWithValue = setOf("-i", "-o", "-e"))
            "timeout" -> inner(args, ctx, depth, flagsWithValue = setOf("-s", "--signal", "-k", "--kill-after"), positionalToSkip = 1)
            "busybox" -> args.firstOrNull()?.let { checkCommand(it, args.drop(1), ctx, depth + 1) }
            "find" -> checkFindExec(args, ctx, depth)
            "awk", "gawk", "mawk", "nawk" -> checkAwk(name, args, ctx)
            "git" -> checkGit(args, ctx)
        }
    }

    /** `env`, `xargs`, `nice`…: skip the wrapper's own options, then check the program it starts. */
    private fun inner(
        args: List<Tok.Word>,
        ctx: Ctx,
        depth: Int,
        skipAssignments: Boolean = false,
        flagsWithValue: Set<String> = emptySet(),
        positionalToSkip: Int = 0,
    ) {
        var i = 0
        var positional = positionalToSkip
        while (i < args.size) {
            val a = args[i]
            when {
                a.value == "--" -> { i++; break }
                a.value.startsWith("-") && a.value.length > 1 -> i += if (a.value in flagsWithValue) 2 else 1
                skipAssignments && a.isAssignment() -> i++
                positional > 0 -> { positional--; i++ }
                else -> break
            }
        }
        if (i < args.size) checkCommand(args[i], args.subList(i + 1, args.size), ctx, depth + 1)
    }

    /** `find … -exec cmd {} \;` runs cmd. */
    private fun checkFindExec(args: List<Tok.Word>, ctx: Ctx, depth: Int) {
        var i = 0
        while (i < args.size) {
            if (args[i].value in setOf("-exec", "-execdir", "-ok", "-okdir") && i + 1 < args.size) {
                val end = (i + 1 until args.size).firstOrNull { args[it].value == ";" || args[it].value == "+" } ?: args.size
                checkCommand(args[i + 1], args.subList(i + 2, end), ctx, depth + 1)
                i = end
            }
            i++
        }
    }

    private val AWK_STRING = Regex("\"(?:\\\\.|[^\"\\\\])*\"")
    // Matched after string literals are blanked to "" (see checkAwk).
    private val AWK_RUNS_PROGRAM = Regex(
        "\\bsystem\\s*\\(" + //           system("…")
            "|\\|\\s*&?\\s*getline" + //   "cmd" | getline, "cmd" |& getline
            "|\\|&" + //                   gawk coprocess
            "|(?<!\\|)\\|(?!\\|)\\s*\"\"", // print … | "cmd"   (but not the `||` operator)
    )

    /** awk can start programs: `system("sh")`, `"cmd" | getline`, `print | "sh"`. */
    private fun checkAwk(name: String, args: List<Tok.Word>, ctx: Ctx) {
        val programs = args.map { it.value }.toMutableList()
        // `awk -f prog.awk`: the program lives in a file — scan that too.
        args.forEachIndexed { i, a ->
            if (a.value == "-f" && i + 1 < args.size) {
                val f = resolve(args[i + 1].value, ctx.cwd)
                if (f != null && f.isFile && f.length() <= MAX_SCRIPT_BYTES) {
                    runCatching { programs += f.readText() }
                }
            }
        }
        for (p in programs) {
            // Blank out string literals first so `printf "a|b"` doesn't look like a pipe.
            val code = AWK_STRING.replace(p, "\"\"")
            if (AWK_RUNS_PROGRAM.containsMatchIn(code)) {
                ctx.refuse("this $name program starts other programs (system / pipe), which isn't allowed here")
                return
            }
        }
    }

    /** Git settings whose value is a command git will run (an alias starting with `!`, a pager…). */
    private val GIT_RISKY_SETTINGS = listOf(
        "alias.", "core.pager", "core.editor", "core.sshcommand", "core.hookspath",
        "core.fsmonitor", "sequence.editor", "pager.", "diff.external",
    )

    /** git aliases starting with `!` and a few settings run shell commands. */
    private fun checkGit(args: List<Tok.Word>, ctx: Ctx) {
        val values = args.map { it.value }
        val risky = GIT_RISKY_SETTINGS
        for ((i, v) in values.withIndex()) {
            val setting = when {
                v == "-c" -> values.getOrNull(i + 1)
                v.startsWith("-c") -> v.removePrefix("-c")
                v == "--config-env" -> values.getOrNull(i + 1)
                else -> null
            }?.lowercase()
            if (setting != null && risky.any { setting.startsWith(it) }) {
                ctx.refuse("'git -c $setting' can run other programs, so it isn't allowed here")
                return
            }
        }
        if ("config" in values && values.any { v -> risky.any { v.lowercase().startsWith(it) } }) {
            ctx.refuse("changing git aliases, pager or editor settings isn't allowed here")
        }
    }

    // --- scripts ---------------------------------------------------------------

    private fun checkScriptRun(how: String, path: String?, ctx: Ctx, depth: Int) {
        if (!ctx.policy.scripts) {
            ctx.refuse("running scripts isn't allowed in this exercise")
            return
        }
        if (path == null) {
            ctx.refuse("'$how' needs a script file")
            return
        }
        val file = resolve(path, ctx.cwd)
        if (file == null || !file.isFile) {
            // Nothing to scan: the shell will just report "not found".
            return
        }
        if (file.length() > MAX_SCRIPT_BYTES) {
            ctx.refuse("the script '$path' is too large to check")
            return
        }
        val text = try {
            file.readText()
        } catch (e: Exception) {
            ctx.refuse("the script '$path' can't be read, so it can't be checked")
            return
        }
        // Relative paths inside the script resolve against the shell's directory, not the script's.
        val inner = Ctx(ctx.policy, ctx.cwd)
        checkText(stripHeredocs(text), inner, depth + 1)
        ctx.commands += inner.commands
        inner.reason?.let { ctx.refuse("the script '$path' runs something not allowed: $it") }
    }

    private val HEREDOC = Regex("""(?<!<)<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")

    /** Drop here-document bodies: they're data fed to a command, not commands. */
    internal fun stripHeredocs(text: String): String {
        val out = StringBuilder()
        val lines = text.split('\n')
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            out.append(line).append('\n')
            val m = HEREDOC.find(line)
            i++
            if (m != null && !line.trimStart().startsWith("#")) {
                val end = m.groupValues[2]
                while (i < lines.size && lines[i].trim() != end) i++
                i++ // the terminator line
            }
        }
        return out.toString()
    }

    private fun looksLikeScript(file: File): Boolean {
        if (file.extension.lowercase() in setOf("sh", "bash")) return true
        return try {
            file.inputStream().use { s ->
                val head = ByteArray(512)
                val n = s.read(head)
                n > 0 && (head[0] == '#'.code.toByte() && n > 1 && head[1] == '!'.code.toByte() ||
                    (0 until n).none { head[it] == 0.toByte() })
            }
        } catch (e: Exception) {
            false
        }
    }

    // --- helpers -----------------------------------------------------------------

    private val WINDOWS_EXTS = listOf(".exe", ".com", ".bat", ".cmd")

    /** `/usr/bin/Python3.EXE` → `python3`. Names are compared lowercase on every OS. */
    internal fun normalize(word: String): String {
        var name = word.substringAfterLast('/').substringAfterLast('\\').lowercase()
        for (ext in WINDOWS_EXTS) {
            if (name.endsWith(ext) && name.length > ext.length) name = name.dropLast(ext.length)
        }
        return name
    }

    private fun isPath(word: String) = '/' in word || '\\' in word

    private fun resolve(path: String, cwd: File?): File? {
        val expanded = if (path == "~" || path.startsWith("~/")) System.getProperty("user.home") + path.drop(1) else path
        val f = File(expanded)
        return when {
            f.isAbsolute -> f
            cwd != null -> File(cwd, path)
            else -> null
        }
    }

    // --- tokenizer -----------------------------------------------------------------

    sealed class Tok {
        /** A shell word. [value] has quotes and escapes removed. */
        data class Word(
            val value: String,
            val raw: String,
            /** Contains a `$` expansion or command substitution outside single quotes. */
            val dynamic: Boolean,
            /** Contains an unquoted `*`, `?` or `[`. */
            val glob: Boolean,
            /** Any part of it was quoted or escaped (so it can't be a reserved word). */
            val quoted: Boolean,
        ) : Tok() {
            fun isAssignment(): Boolean {
                val eq = raw.indexOf('=')
                return eq > 0 && ASSIGN_NAME.matches(raw.substring(0, eq))
            }
        }

        /** A control operator (`|`, `&&`, `;`, `(`…), or `"redir"` for `>`, `2>&1`, `<`…. */
        data class Op(val op: String) : Tok()
    }

    private val ASSIGN_NAME = Regex("[A-Za-z_][A-Za-z0-9_]*")

    /** One pass over the text: words, operators, and the bodies of every `$(…)` / backtick / `<(…)`. */
    private class Scanner(val s: String) {
        val tokens = mutableListOf<Tok>()
        val substitutions = mutableListOf<String>()
        var problem: String? = null

        private var i = 0
        private val value = StringBuilder()
        private val raw = StringBuilder()
        private var inWord = false
        private var dynamic = false
        private var glob = false
        private var quoted = false

        fun run() {
            while (i < s.length) {
                val c = s[i]
                when {
                    c == ' ' || c == '\t' -> { endWord(); i++ }
                    c == '\n' || c == '\r' -> { endWord(); tokens += Tok.Op(";"); i++ }
                    c == '#' && !inWord -> { while (i < s.length && s[i] != '\n') i++ }
                    c == '\'' -> singleQuoted()
                    c == '"' -> doubleQuoted()
                    c == '\\' -> {
                        start(); quoted = true
                        if (i + 1 < s.length) {
                            if (s[i + 1] != '\n') { value.append(s[i + 1]); raw.append(c).append(s[i + 1]) }
                            i += 2
                        } else {
                            i++
                        }
                    }
                    c == '$' -> dollar()
                    c == '`' -> backtick()
                    (c == '<' || c == '>') && i + 1 < s.length && s[i + 1] == '(' -> {
                        // Process substitution <(cmd) / >(cmd): an argument whose body is a command.
                        start(); dynamic = true
                        val end = matchParen(i + 2)
                        substitutions += s.substring(i + 2, end.coerceAtMost(s.length))
                        raw.append(s, i, (end + 1).coerceAtMost(s.length))
                        i = end + 1
                    }
                    c == '<' || c == '>' -> redirection()
                    c == '&' && i + 1 < s.length && s[i + 1] == '>' -> redirection()
                    c == '|' || c == '&' || c == ';' || c == '(' || c == ')' -> operator()
                    else -> {
                        start()
                        if (c == '*' || c == '?' || c == '[') glob = true
                        value.append(c); raw.append(c); i++
                    }
                }
            }
            endWord()
        }

        private fun start() {
            inWord = true
        }

        private fun endWord() {
            if (inWord) tokens += Tok.Word(value.toString(), raw.toString(), dynamic, glob, quoted)
            value.clear(); raw.clear()
            inWord = false; dynamic = false; glob = false; quoted = false
        }

        private fun operator() {
            endWord()
            val two = if (i + 1 < s.length) s.substring(i, i + 2) else ""
            val op = if (two in setOf("&&", "||", ";;", "|&")) two else s[i].toString()
            tokens += Tok.Op(op)
            i += op.length
        }

        /** `>`, `>>`, `2>&1`, `&>`, `<`, `<<`, `<<<`… A preceding all-digit word is the fd number. */
        private fun redirection() {
            if (inWord && raw.all { it.isDigit() }) {
                value.clear(); raw.clear(); inWord = false; dynamic = false; glob = false; quoted = false
            } else {
                endWord()
            }
            val startAt = i
            if (s[i] == '&') i++
            while (i < s.length && (s[i] == '<' || s[i] == '>') && i - startAt < 3) i++
            if (i < s.length && (s[i] == '&' || s[i] == '|')) i++
            if (i < s.length && s[i] == '-') i++ // <<- here-doc, >&- close
            tokens += Tok.Op("redir")
            // `>&2`, `<&-`: the fd target is glued on; it's harmless and becomes the target word.
        }

        private fun singleQuoted() {
            start(); quoted = true
            val end = s.indexOf('\'', i + 1).let { if (it < 0) s.length else it }
            value.append(s, i + 1, end)
            raw.append(s, i, (end + 1).coerceAtMost(s.length))
            if (end >= s.length) problem = problem ?: "a quote ' is never closed"
            i = end + 1
        }

        private fun doubleQuoted() {
            start(); quoted = true
            raw.append('"')
            i++
            while (i < s.length && s[i] != '"') {
                val c = s[i]
                when {
                    c == '\\' && i + 1 < s.length -> {
                        val n = s[i + 1]
                        if (n in "\$`\"\\\n") value.append(n) else value.append(c).append(n)
                        raw.append(c).append(n)
                        i += 2
                    }
                    c == '$' -> dollar()
                    c == '`' -> backtick()
                    else -> { value.append(c); raw.append(c); i++ }
                }
            }
            if (i >= s.length) problem = problem ?: "a quote \" is never closed"
            raw.append('"')
            i++
        }

        private fun dollar() {
            start()
            val n = if (i + 1 < s.length) s[i + 1] else ' '
            when {
                n == '(' && i + 2 < s.length && s[i + 2] == '(' -> {
                    // $(( arithmetic )): not a command, but it may hide one. Scanning
                    // from the second '(' finds the closing '))' as one balanced pair.
                    dynamic = true
                    val end = matchParen(i + 2)
                    collectNested(s.substring(i + 3, (end - 1).coerceIn(i + 3, s.length)))
                    raw.append(s, i, (end + 1).coerceAtMost(s.length))
                    i = end + 1
                }
                n == '(' -> {
                    dynamic = true
                    val end = matchParen(i + 2)
                    substitutions += s.substring(i + 2, end.coerceAtMost(s.length))
                    raw.append(s, i, (end + 1).coerceAtMost(s.length))
                    i = end + 1
                }
                n == '{' -> {
                    dynamic = true
                    val end = matchBrace(i + 2)
                    collectNested(s.substring(i + 2, end.coerceAtMost(s.length)))
                    raw.append(s, i, (end + 1).coerceAtMost(s.length))
                    i = end + 1
                }
                n == '\'' -> {
                    // $'…' ANSI-C quoting: literal text with escapes.
                    quoted = true
                    val end = s.indexOf('\'', i + 2).let { if (it < 0) s.length else it }
                    value.append(s, i + 2, end)
                    raw.append(s, i, (end + 1).coerceAtMost(s.length))
                    i = end + 1
                }
                n.isLetterOrDigit() || n == '_' || n in "@*#?$!-" -> {
                    dynamic = true
                    var j = i + 1
                    if (n.isLetter() || n == '_') {
                        while (j < s.length && (s[j].isLetterOrDigit() || s[j] == '_')) j++
                    } else {
                        j++
                    }
                    value.append(s, i, j); raw.append(s, i, j)
                    i = j
                }
                else -> { value.append('$'); raw.append('$'); i++ }
            }
        }

        private fun backtick() {
            start(); dynamic = true
            var j = i + 1
            val body = StringBuilder()
            while (j < s.length && s[j] != '`') {
                if (s[j] == '\\' && j + 1 < s.length) { body.append(s[j + 1]); j += 2 } else { body.append(s[j]); j++ }
            }
            substitutions += body.toString()
            raw.append(s, i, (j + 1).coerceAtMost(s.length))
            i = j + 1
        }

        /** Find `$(`, backticks and `<(` inside an arithmetic or `${…}` body. */
        private fun collectNested(text: String) {
            if ('$' !in text && '`' !in text && "<(" !in text) return
            val inner = Scanner(text).also { it.run() }
            substitutions += inner.substitutions
        }

        /** Index of the `)` closing a paren opened just before [from]; honors quotes and nesting. */
        private fun matchParen(from: Int): Int {
            var depth = 1
            var j = from
            while (j < s.length) {
                when (s[j]) {
                    '\\' -> j++
                    '\'' -> j = s.indexOf('\'', j + 1).let { if (it < 0) s.length else it }
                    '"' -> {
                        j++
                        while (j < s.length && s[j] != '"') { if (s[j] == '\\') j++; j++ }
                    }
                    '(' -> depth++
                    ')' -> { depth--; if (depth == 0) return j }
                }
                j++
            }
            problem = problem ?: "a '(' is never closed"
            return s.length
        }

        private fun matchBrace(from: Int): Int {
            var depth = 1
            var j = from
            while (j < s.length) {
                when (s[j]) {
                    '\\' -> j++
                    '{' -> depth++
                    '}' -> { depth--; if (depth == 0) return j }
                }
                j++
            }
            problem = problem ?: "a '{' is never closed"
            return s.length
        }
    }
}
