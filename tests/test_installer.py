"""Standalone raw-download installer exercised with local Git repositories."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_setup import ROOT


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-installer-')
        self.home = Path(self.tmp.name)
        self.source = self.home / 'source'
        self.source.mkdir()
        self.destination = self.home / 'installed checkout'
        self.log = self.home / 'bootstrap-args'
        self.git('init', '-q', '-b', 'main', str(self.source))
        self.git('-C', str(self.source), 'config', 'user.name', 'Test')
        self.git('-C', str(self.source), 'config', 'user.email', 'test@example.test')
        bootstrap = self.source / 'bootstrap.sh'
        bootstrap.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_LOG"\nexit "${TEST_EXIT:-0}"\n')
        bootstrap.chmod(0o755)
        self.git('-C', str(self.source), 'add', '.')
        self.git('-C', str(self.source), 'commit', '-qm', 'fixture')
        self.script = self.home / 'downloaded-install.sh'
        shutil.copy2(ROOT / 'install.sh', self.script)
        self.env = dict(os.environ, HOME=str(self.home), DOTFILES_REPO=str(self.source),
                        DOTFILES_DIR=str(self.destination), TEST_LOG=str(self.log))
        self.env.pop('DOTFILES_REF', None)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()

    def install(self, *args, success=True):
        result = subprocess.run(['sh', str(self.script), *args], cwd=self.home, env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_standalone_download_clones_and_forwards_arguments(self):
        self.install('install', '--modules', 'shell,git')
        self.assertEqual(self.log.read_text(), 'install\n--modules\nshell,git\n')
        self.assertEqual(self.git('-C', str(self.destination), 'remote', 'get-url', 'origin'), str(self.source))

    def test_buffered_curl_style_execution_works_from_any_directory(self):
        result = subprocess.run(['sh', '-c', self.script.read_text(), '--', 'preview', '--modules', 'git'],
                                cwd=self.home, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'preview\n--modules\ngit\n')

    def test_existing_matching_checkout_preserves_local_changes(self):
        self.install('preview')
        local = self.destination / 'uncommitted'
        local.write_text('keep')
        self.install('doctor')
        self.assertEqual(local.read_text(), 'keep')
        self.assertEqual(self.log.read_text(), 'doctor\n')

    def test_existing_unrelated_destination_is_preserved(self):
        self.destination.mkdir()
        keep = self.destination / 'keep'
        keep.write_text('original')
        self.install('install', success=False)
        self.assertEqual(keep.read_text(), 'original')
        self.assertFalse(self.log.exists())

    def test_failed_clone_cleans_staging_and_leaves_no_destination(self):
        self.env['DOTFILES_REF'] = 'missing-branch'
        self.install('install', success=False)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.home.glob('.dotfiles-install.*')), [])

    def test_existing_other_branch_is_rejected(self):
        self.install('preview')
        self.git('-C', str(self.destination), 'checkout', '-qb', 'other')
        self.log.unlink()
        self.install('install', success=False)
        self.assertFalse(self.log.exists())

    def test_bootstrap_failure_is_propagated(self):
        self.env['TEST_EXIT'] = '42'
        self.assertEqual(self.install('install', success=False).returncode, 42)
        self.assertTrue((self.destination / '.git').exists())

    def test_default_destination_is_under_home(self):
        self.env.pop('DOTFILES_DIR')
        self.install('preview')
        self.assertTrue((self.home / '.local/share/dotfiles/.git').exists())
