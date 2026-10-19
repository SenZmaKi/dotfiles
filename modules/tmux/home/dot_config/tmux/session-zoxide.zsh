#!/bin/zsh
# Resolve first so missing matches and panes already in the project stay quiet.
target_dir=$(zoxide query -- "$1" 2>/dev/null) || exit 0
pane_dir=$(tmux -S "$3" display-message -p -t "$2" '#{pane_current_path}') || exit 0
[[ "${target_dir:A}" == "${pane_dir:A}" ]] && exit 0

# Use the resolved path so zoxide does not exclude the shell's current directory.
printf -v jump_command 'builtin cd -- %q' "$target_dir"
tmux -S "$3" send-keys -t "$2" -l "$jump_command"
tmux -S "$3" send-keys -t "$2" Enter
