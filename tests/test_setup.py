import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dotfiles_setup', ROOT / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SelectionTests(unittest.TestCase):
    def test_dependencies_and_duplicates(self):
        self.assertEqual(setup.select(['tmux', 'shell', 'git'], 'Linux'), ['shell', 'tmux', 'git'])

    def test_macos_module_skipped_on_linux(self):
        self.assertNotIn('macos', setup.select(setup.MANIFEST['profiles']['workstation'], 'Linux'))

    def test_unknown_module(self):
        with self.assertRaises(ValueError):
            setup.select(['typo'], 'Darwin')


@unittest.skipUnless(shutil.which('chezmoi'), 'requires real chezmoi')
class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.state = self.home / '.local/state/dotfiles'

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args, success=True):
        result = subprocess.run([str(ROOT / 'setup'), *args, '--home', str(self.home)], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_preview_is_read_only(self):
        self.invoke('preview', '--modules', 'shell,git')
        self.assertEqual(list(self.home.iterdir()), [])

    def test_selection_isolation_idempotency_and_identity(self):
        (self.home / '.gitconfig').write_text('[user]\n name = Example\n email = example@example.com\n')
        unrelated = self.home / '.config/gh/hosts.yml'
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('DO NOT MODIFY')
        for _ in range(2):
            self.invoke('install', '--modules', 'git', '--configs-only')
        self.assertFalse((self.home / '.zshrc').exists())
        self.assertIn('example@example.com', (self.home / '.gitconfig.local').read_text())
        self.assertEqual(unrelated.read_text(), 'DO NOT MODIFY')
        self.assertEqual(json.loads((self.state / 'selection.json').read_text()), ['git'])
        self.assertEqual((self.home / '.config/gh').stat().st_mode & 0o777, 0o700)
        result = self.invoke('preview')
        self.assertNotIn('diff --git', result.stdout)

    def test_restore_directory_git_metadata_symlink_and_absent_files(self):
        nvim = self.home / '.config/nvim'
        (nvim / '.git').mkdir(parents=True)
        (nvim / '.git/marker').write_text('existing repo')
        link = self.home / '.config/tmux/tmux.conf'
        link.parent.mkdir(parents=True)
        link.symlink_to('old-missing-target')
        self.invoke('install', '--modules', 'nvim,tmux', '--configs-only')
        original = sorted((self.state / 'backups').iterdir())[0]
        self.assertEqual((nvim / '.git/marker').read_text(), 'existing repo')
        self.invoke('restore', '--backup', str(original))
        self.assertEqual(os.readlink(link), 'old-missing-target')
        self.assertEqual((nvim / '.git/marker').read_text(), 'existing repo')
        self.assertFalse((nvim / 'init.lua').exists())
        self.assertFalse((self.home / '.zshrc').exists())
        self.assertFalse((self.state / 'selection.json').exists())

    def test_corrupt_backup_rejected_before_deletion(self):
        (self.home / '.gitconfig').write_text('original')
        self.invoke('backup', '--modules', 'git')
        directory = next((self.state / 'backups').iterdir())
        (directory / 'files/.gitconfig').unlink()
        self.invoke('restore', '--backup', str(directory), success=False)
        self.assertEqual((self.home / '.gitconfig').read_text(), 'original')

    def test_all_configuration_and_shell_start_without_optional_tools(self):
        self.invoke('install', '--profile', 'workstation', '--configs-only')
        env = dict(os.environ, HOME=str(self.home), ZDOTDIR=str(self.home), PATH='/usr/bin:/bin', TERM='dumb')
        shell = subprocess.run(['zsh', '-i', '-c', 'print READY'], env=env, capture_output=True, text=True)
        self.assertEqual(shell.returncode, 0, shell.stderr)
        self.assertIn('READY', shell.stdout)
        self.assertNotIn('command not found', shell.stderr)


if __name__ == '__main__':
    unittest.main()
