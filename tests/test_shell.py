"""Run real Zsh with an isolated HOME and controlled helper executables."""
import os
import pty
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_setup import ROOT

ZSH = shutil.which('zsh')
SOURCE = ROOT / 'modules/shell/home/dot_zshrc'


@unittest.skipUnless(ZSH, 'requires Zsh')
class ShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles shell ')
        self.home = Path(self.tmp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.log = self.home / 'helper.log'
        self.env = dict(HOME=str(self.home), ZDOTDIR=str(self.home), PATH=str(self.bin),
                        TERM='dumb', TEST_LOG=str(self.log), DOTFILES_TMUX_AUTO_ATTACH='0', DOTFILES_FASTFETCH='0')

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, name, body):
        dest = self.bin / name
        dest.write_text('#!/bin/sh\n' + body + '\n')
        dest.chmod(0o755)

    def shell(self, body, success=True, env=None):
        result = subprocess.run([ZSH, '-dfi', '-c', 'source "$1"; ' + body, 'test', str(SOURCE)],
                                env=dict(self.env, **(env or {})), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_minimal_shell_is_quiet(self):
        result = self.shell('print READY')
        self.assertEqual(result.stdout, 'READY\n')
        self.assertEqual(result.stderr, '')

    def test_local_overrides_control_startup(self):
        local = self.home / '.config/zsh/local.zsh'
        local.parent.mkdir(parents=True)
        local.write_text('DOTFILES_TMUX_AUTO_ATTACH=0\nDOTFILES_FASTFETCH=0\nalias custom="print LOCAL"\n')
        result = self.shell('eval custom; print $DOTFILES_TMUX_AUTO_ATTACH')
        self.assertEqual(result.stdout, 'LOCAL\n0\n')

    def test_pbcopy_receives_exact_stdin(self):
        self.tool('pbcopy', '/bin/cat > "$TEST_LOG"')
        self.shell('print -rn -- "clip text" | clipcopy')
        self.assertEqual(self.log.read_text(), 'clip text')

    def test_wayland_clipboard(self):
        self.tool('wl-copy', '/bin/cat > "$TEST_LOG"')
        self.shell('print -rn -- wayland | clipcopy', env={'WAYLAND_DISPLAY': 'wayland-0'})
        self.assertEqual(self.log.read_text(), 'wayland')

    def test_x11_clipboard_arguments(self):
        self.tool('xclip', 'printf "%s\\n" "$@" > "$TEST_LOG"; /bin/cat >> "$TEST_LOG"')
        self.shell('print -rn -- x11 | clipcopy', env={'DISPLAY': ':1'})
        self.assertEqual(self.log.read_text(), '-selection\nclipboard\nx11')

    def test_headless_clipboard_explains_failure(self):
        self.assertIn('No clipboard available', self.shell('clipcopy', success=False).stderr)

    def test_macos_opener_preserves_spaces(self):
        self.tool('open', 'printf "%s\\n" "$@" > "$TEST_LOG"')
        self.shell('OSTYPE=darwin; open_path "/a path/file"')
        self.assertEqual(self.log.read_text(), '/a path/file\n')

    def test_linux_opener_preserves_spaces(self):
        self.tool('xdg-open', 'printf "%s\\n" "$@" > "$TEST_LOG"')
        self.shell('OSTYPE=linux-gnu; open_path "/a path/file"')
        self.assertEqual(self.log.read_text(), '/a path/file\n')

    def test_headless_opener_explains_failure(self):
        self.assertIn('No desktop opener', self.shell('OSTYPE=linux-gnu; open_path .', success=False).stderr)

    def test_editor_uses_nvim_when_available(self):
        self.tool('nvim', 'exit 0')
        self.assertEqual(self.shell('print $EDITOR:$SUDO_EDITOR').stdout, 'nvim:nvim\n')

    def test_ssh_editor_uses_vi(self):
        self.tool('nvim', 'exit 0')
        self.assertEqual(self.shell('print $EDITOR:$SUDO_EDITOR', env={'SSH_CONNECTION': 'test'}).stdout, 'vi:vi\n')

    def test_missing_editor_falls_back_to_vi(self):
        self.assertEqual(self.shell('print $EDITOR:$SUDO_EDITOR').stdout, 'vi:vi\n')

    def test_lf_changes_to_directory_with_spaces_and_removes_temp(self):
        dest = self.home / 'directory with spaces'
        dest.mkdir()
        for command in ('mktemp', 'cat', 'rm'):
            (self.bin / command).symlink_to(shutil.which(command))
        self.tool('lf', 'printf "%s" "$LF_DEST" > "${1#-last-dir-path=}"; printf "%s" "${1#-last-dir-path=}" > "$TEST_LOG"')
        result = self.shell('lfcd; print -r -- "$PWD"', env={'LF_DEST': str(dest)})
        self.assertEqual(result.stdout.strip(), str(dest))
        self.assertFalse(Path(self.log.read_text()).exists())

    def test_lf_missing_returns_127(self):
        result = self.shell('lfcd', success=False)
        self.assertEqual(result.returncode, 127)

    def test_key_generation_is_urlsafe_and_has_no_newline(self):
        self.tool('openssl', 'printf "ab+/cd==\\n"')
        (self.bin / 'tr').symlink_to(shutil.which('tr'))
        self.tool('pbcopy', '/bin/cat > "$TEST_LOG"')
        self.shell('makekey')
        self.assertEqual(self.log.read_text(), 'ab-_cd')

    def test_key_generator_failure_propagates(self):
        self.tool('openssl', 'exit 12')
        (self.bin / 'tr').symlink_to(shutil.which('tr'))
        self.tool('pbcopy', '/bin/cat > "$TEST_LOG"')
        self.shell('makekey', success=False)

    def test_tmux_never_attaches_without_tty(self):
        self.tool('tmux', 'printf CALLED > "$TEST_LOG"')
        self.shell('true', env={'TERM': 'xterm-256color', 'DOTFILES_TMUX_AUTO_ATTACH': '1'})
        self.assertFalse(self.log.exists())

    def test_fastfetch_disabled_and_non_tty_remains_quiet(self):
        self.tool('fastfetch', 'printf CALLED > "$TEST_LOG"')
        self.shell('true', env={'TERM': 'xterm-256color', 'DOTFILES_FASTFETCH': '1'})
        self.assertFalse(self.log.exists())

    def shell_tty(self, env=None):
        master, slave = pty.openpty()
        try:
            result = subprocess.run([ZSH, '-dfi', '-c', 'source "$1"; print BODY', 'test', str(SOURCE)],
                                    stdin=slave, env=dict(self.env, TERM='xterm-256color', **(env or {})),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result
        finally:
            os.close(master)
            os.close(slave)

    def test_tty_tmux_attaches_to_most_recent_session(self):
        for command in ('sort', 'awk'):
            (self.bin / command).symlink_to(shutil.which(command))
        self.tool('tmux', 'if [ "$1" = list-sessions ]; then printf "older 10\\nrecent 30\\n"; else printf "%s\\n" "$@" > "$TEST_LOG"; fi')
        result = self.shell_tty({'DOTFILES_TMUX_AUTO_ATTACH': '1'})
        self.assertEqual(self.log.read_text(), '-u\nattach\n-t\nrecent\n')
        self.assertNotIn('BODY', result.stdout)

    def test_tty_tmux_creates_main_when_no_sessions(self):
        for command in ('sort', 'awk'):
            (self.bin / command).symlink_to(shutil.which(command))
        self.tool('tmux', 'if [ "$1" = list-sessions ]; then exit 1; else printf "%s\\n" "$@" > "$TEST_LOG"; fi')
        self.shell_tty({'DOTFILES_TMUX_AUTO_ATTACH': '1'})
        self.assertEqual(self.log.read_text(), '-u\nnew\n-s\nmain\n')

    def test_tty_inside_tmux_never_attaches_again(self):
        self.tool('tmux', 'printf CALLED > "$TEST_LOG"')
        result = self.shell_tty({'DOTFILES_TMUX_AUTO_ATTACH': '1', 'TMUX': 'already-inside'})
        self.assertIn('BODY', result.stdout)
        self.assertFalse(self.log.exists())

    def test_oh_my_zsh_automatic_updates_disabled(self):
        result = self.shell('zstyle -s ":omz:update" mode mode; print $mode')
        self.assertEqual(result.stdout, 'disabled\n')
