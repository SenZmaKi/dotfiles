"""Real tmux sessions on a dedicated socket; never connect to the user's server."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from test_setup import ROOT


@unittest.skipUnless(shutil.which('tmux') and shutil.which('zsh'), 'requires tmux and Zsh')
class TmuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-tmux-')
        self.home = Path(self.tmp.name)
        self.target = self.home / 'project with spaces'
        self.target.mkdir()
        self.socket = self.home / 'socket'
        config = self.home / '.config/tmux'
        config.mkdir(parents=True)
        source = ROOT / 'modules/tmux/home/dot_config/tmux'
        shutil.copy2(source / 'tmux.conf.local', config / 'tmux.conf.local')
        shutil.copy2(source / 'session-zoxide.zsh', config / 'session-zoxide.zsh')
        tpm = config / 'plugins/tpm/tpm'
        tpm.parent.mkdir(parents=True)
        tpm.write_text('#!/bin/sh\nexit 0\n')
        tpm.chmod(0o755)
        bin_dir = self.home / 'bin'
        bin_dir.mkdir()
        query = bin_dir / 'zoxide'
        query.write_text('#!/bin/sh\nprintf "%s\\n" "$TARGET_DIR"\n')
        query.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), ZDOTDIR=str(self.home),
                        PATH=str(bin_dir) + ':' + os.environ['PATH'], TERM='xterm-256color',
                        TARGET_DIR=str(self.target), DOTFILES_TMUX_AUTO_ATTACH='0', DOTFILES_FASTFETCH='0')
        for variable in ('TMUX', 'TMUX_CONF', 'TMUX_CONF_LOCAL', 'TMUX_PLUGIN_MANAGER_PATH'):
            self.env.pop(variable, None)
        wrapper = self.home / 'test-shell'
        wrapper.write_text('#!/bin/sh\nexec ' + shutil.which('zsh') + ' -df "$@"\n')
        wrapper.chmod(0o755)
        initial = self.home / 'initial.conf'
        initial.write_text('set-option -g default-shell ' + str(wrapper) + '\n')
        self.tmux('-f', str(initial), 'new-session', '-d', '-s', 'main', '-c', str(self.home))
        self.tmux('source-file', str(config / 'tmux.conf.local'))

    def tearDown(self):
        subprocess.run(['tmux', '-S', str(self.socket), 'kill-server'], env=self.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait for shell exit handlers before removing their home.
        deadline = time.monotonic() + 3
        while True:
            try:
                self.tmp.cleanup()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def tmux(self, *args):
        return subprocess.check_output(['tmux', '-S', str(self.socket), *args],
                                       env=self.env, text=True, stderr=subprocess.PIPE, timeout=10).strip()

    def wait_for_directory(self, pane, expected):
        deadline = time.monotonic() + 5
        actual = None
        while time.monotonic() < deadline:
            actual = self.tmux('display-message', '-p', '-t', pane, '#{pane_current_path}')
            if Path(actual).resolve() == expected.resolve():
                return
            time.sleep(0.05)
        self.fail(f'{pane}: expected {expected}, got {actual}')

    def test_prefix_and_bindings_loaded(self):
        self.assertEqual(self.tmux('show-options', '-gv', 'prefix'), 'M-o')
        self.assertIn('session-zoxide.zsh', self.tmux('show-hooks', '-g', 'after-new-window'))
        self.assertIn('session-zoxide.zsh', self.tmux('show-hooks', '-g', 'after-new-session'))

    def test_new_session_jumps_to_matching_project(self):
        pane = self.tmux('new-session', '-d', '-P', '-F', '#{pane_id}', '-s', 'project', '-c', str(self.home))
        self.wait_for_directory(pane, self.target)

    def test_new_window_jumps_to_matching_project(self):
        self.tmux('new-session', '-d', '-s', 'project', '-c', str(self.home))
        pane = self.tmux('new-window', '-d', '-P', '-F', '#{pane_id}', '-t', 'project', '-c', str(self.home))
        self.wait_for_directory(pane, self.target)

    def test_main_session_windows_stay_in_requested_directory(self):
        pane = self.tmux('new-window', '-d', '-P', '-F', '#{pane_id}', '-t', 'main', '-c', str(self.home))
        time.sleep(0.2)
        self.wait_for_directory(pane, self.home)

    def test_explicit_command_is_not_replaced_by_directory_jump(self):
        pane = self.tmux('new-session', '-d', '-P', '-F', '#{pane_id}', '-s', 'explicit', '-c', str(self.home), 'sleep 20')
        time.sleep(0.2)
        self.wait_for_directory(pane, self.home)
        self.assertEqual(self.tmux('display-message', '-p', '-t', pane, '#{pane_start_command}').strip('"'), 'sleep 20')
        self.assertNotIn('builtin cd', self.tmux('capture-pane', '-p', '-t', pane))

    def test_helper_is_quiet_for_unmatched_project(self):
        query = self.home / 'bin/zoxide'
        query.write_text('#!/bin/sh\nexit 1\n')
        pane = self.tmux('new-session', '-d', '-P', '-F', '#{pane_id}', '-s', 'missing', '-c', str(self.home))
        time.sleep(0.2)
        self.wait_for_directory(pane, self.home)
