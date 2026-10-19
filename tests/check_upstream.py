#!/usr/bin/env python3
"""Optional live upstream checks. All downloads/configuration use a temporary home."""
import importlib.util
import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dotfiles_setup', ROOT / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

with tempfile.TemporaryDirectory(prefix='dotfiles-upstream-') as tmp:
    home = Path(tmp)
    setup.install_plugins(['shell', 'tmux'], home)
    locks = setup.json.loads((ROOT / 'plugins.lock.json').read_text())
    for plugin in locks:
        commit = subprocess.check_output(['git', '-C', str(home / plugin['path']), 'rev-parse', 'HEAD'], text=True).strip()
        assert commit == plugin['commit'], plugin['path']
    print('PASS all seven upstream plugin commits exist and checked out', flush=True)
    subprocess.run([str(ROOT / 'setup'), 'apply', '--modules', 'shell,tmux', '--home', tmp], check=True)
    env = dict(os.environ, HOME=tmp, ZDOTDIR=tmp, TERM='xterm-256color',
               XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
               XDG_STATE_HOME=str(home / '.local/state'), XDG_CACHE_HOME=str(home / '.cache'),
               DOTFILES_TMUX_AUTO_ATTACH='0', DOTFILES_FASTFETCH='0')
    env.pop('TMUX', None)
    master, slave = pty.openpty()
    try:
        shell = subprocess.run([shutil.which('zsh'), '-dfi', '-c',
                                'source "$HOME/.zshrc"; print UPSTREAM_READY'],
                               stdin=slave, env=env, capture_output=True, text=True, timeout=30)
        assert shell.returncode == 0, shell.stderr
        assert 'UPSTREAM_READY' in shell.stdout, shell.stdout
        assert not shell.stderr.strip(), shell.stderr
        print('PASS real upstream shell plugins initialize under Zsh', flush=True)
    finally:
        os.close(master)
        os.close(slave)
