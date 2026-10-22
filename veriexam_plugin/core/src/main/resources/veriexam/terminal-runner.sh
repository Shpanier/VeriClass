# VeriExam terminal runner: runs ONE student command line, then saves the shell
# state (exported variables + working directory) for the next line.
#
# The plugin has already checked the line against the exercise's rules. It
# arrives in VE_CMD, so no quoting is involved. Works in BusyBox sh, bash and
# Git Bash. Shell functions, aliases and `set -o` options don't carry over.

__ve_cmd=$VE_CMD
__ve_state=$VE_STATE
__ve_cwd=$VE_CWD
__ve_cwd_out=$VE_CWD_OUT
unset VE_CMD VE_STATE VE_CWD VE_CWD_OUT

__ve_save() {
    export -p > "$__ve_state.tmp" 2>/dev/null && mv -f "$__ve_state.tmp" "$__ve_state"
    # Git Bash prints /c/Users/...; -W gives C:/Users/... which Java understands.
    { pwd -W 2>/dev/null || pwd; } > "$__ve_cwd_out" 2>/dev/null
}

# Ctrl-C: the command is interrupted, but a `cd` earlier on the line still counts.
__ve_interrupted() {
    __ve_save
    exit 130
}

# Takes the exit status as an argument: a variable set here would be auto-exported.
__ve_finish() {
    set +a
    __ve_save
    exit "$1"
}

if [ -f "$__ve_state" ]; then
    . "$__ve_state" 2>/dev/null
fi
cd "$__ve_cwd" 2>/dev/null
trap __ve_interrupted INT

# Auto-export, so a plain `X=1` survives to the next line like in a real shell.
set -a
eval "$__ve_cmd"
__ve_finish $?
