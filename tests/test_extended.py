"""Broader regression tests. Network/package mutations are replaced by local fixtures."""
import contextlib
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from test_setup import ROOT, setup


class TemporaryHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles test ')
        self.home = Path(self.tmp.name)
        self.state = self.home / '.local/state/dotfiles'

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args, success=True):
        result = subprocess.run([str(ROOT / 'setup'), *args, '--home', str(self.home)],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def snapshots(self):
        return sorted((self.state / 'backups').iterdir())


class ManifestTests(unittest.TestCase):
    def test_source_files_all_have_backup_coverage(self):
        for name, module in setup.MODULES.items():
            base = ROOT / 'modules' / name / 'home'
            self.assertTrue(base.is_dir())
            for path in base.rglob('*'):
                if not path.is_file():
                    continue
                target = '/'.join(part.removeprefix('private_').removeprefix('symlink_').replace('dot_', '.', 1)
                                  for part in path.relative_to(base).parts)
                self.assertTrue(any(target == root or target.startswith(root + '/') for root in module['roots']), target)

    def test_no_credentials_cache_or_nested_git_metadata(self):
        forbidden = {'.git', 'node_modules', 'hosts.yml', 'auth.json', '.DS_Store', '.env', '.zsh_history'}
        for path in (ROOT / 'modules').rglob('*'):
            self.assertNotIn(path.name, forbidden, str(path))
            if path.name != 'tmux.conf.local':
                self.assertFalse(path.name.endswith('.local'), str(path))

    def test_plugin_lock_has_unique_paths_and_exact_commits(self):
        locks = json.loads((ROOT / 'plugins.lock.json').read_text())
        self.assertEqual(len(locks), len({p['path'] for p in locks}))
        for plugin in locks:
            self.assertIn(plugin['module'], setup.MODULES)
            self.assertRegex(plugin['commit'], r'^[0-9a-f]{40}$')
            self.assertTrue(plugin['url'].startswith('https://github.com/'))
            self.assertNotIn('@', plugin['url'])

    def test_profiles_resolve_on_both_platforms(self):
        for system in ('Linux', 'Darwin'):
            for names in setup.MANIFEST['profiles'].values():
                result = setup.select(names, system)
                self.assertEqual(len(result), len(set(result)))
                for name in result:
                    for dependency in setup.MODULES[name].get('dependencies', []):
                        self.assertLess(result.index(dependency), result.index(name))


    def test_all_128_module_subsets_on_both_platforms(self):
        names = list(setup.MODULES)
        with contextlib.redirect_stdout(io.StringIO()):
            for system in ('Linux', 'Darwin'):
                for count in range(len(names) + 1):
                    for subset in itertools.combinations(names, count):
                        selected = setup.select(list(subset), system)
                        self.assertEqual(len(selected), len(set(selected)))
                        for name in selected:
                            self.assertEqual(setup.MODULES[name].get('os', system), system)
                            for dependency in setup.MODULES[name].get('dependencies', []):
                                self.assertLess(selected.index(dependency), selected.index(name))
                        formulae, casks = setup.package_plan(selected, system)
                        self.assertEqual(len(formulae), len(set(formulae)))
                        self.assertEqual(len(casks), len(set(casks)))
                        if system == 'Linux':
                            self.assertEqual(casks, [])

    def test_cycle_reports_actionable_error(self):
        with patch.dict(setup.MODULES, {'a': {'dependencies': ['b']}, 'b': {'dependencies': ['a']}}):
            with self.assertRaisesRegex(ValueError, 'cycle'):
                setup.select(['a'], 'Linux')


@unittest.skipUnless(shutil.which('chezmoi'), 'requires chezmoi')
class LifecycleTests(TemporaryHome):
    def test_each_module_applies_independently(self):
        for module in setup.MODULES:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run([str(ROOT / 'setup'), 'apply', '--modules', module, '--home', tmp], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = setup.select([module], setup.platform.system())
                for path in setup.targets(expected):
                    target = Path(tmp) / path
                    self.assertTrue(target.exists() or target.is_symlink(), path)

    def test_deselect_leaves_files_but_changes_saved_selection(self):
        self.invoke('apply', '--modules', 'shell,git')
        self.invoke('apply', '--modules', 'git')
        self.assertTrue((self.home / '.zshrc').exists())
        self.assertEqual(json.loads((self.state / 'selection.json').read_text()), ['git'])

    def test_invalid_selection_has_no_side_effects(self):
        for names in ('unknown', '', 'shell,unknown'):
            self.invoke('apply', '--modules', names, success=False)
            self.assertEqual(list(self.home.iterdir()), [])

    def test_existing_overrides_are_not_changed(self):
        for path in ('.config/zsh/local.zsh', '.zprofile.local', '.gitconfig.local', '.config/kitty/local.conf'):
            dest = self.home / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text('# KEEP\n')
        self.invoke('apply', '--modules', 'shell,git,kitty')
        for path in ('.config/zsh/local.zsh', '.zprofile.local', '.gitconfig.local', '.config/kitty/local.conf'):
            self.assertEqual((self.home / path).read_text(), '# KEEP\n')

    def test_signing_configuration_survives_migration(self):
        original = self.home / '.gitconfig'
        for key, value in {'user.name': 'Name With Spaces', 'user.email': 'test@example.test',
                           'user.signingkey': 'KEY', 'commit.gpgsign': 'true', 'gpg.format': 'ssh',
                           'gpg.program': '/a path/gpg'}.items():
            subprocess.run(['git', 'config', '--file', str(original), key, value], check=True)
        self.invoke('apply', '--modules', 'git')
        for key, expected in {'user.name': 'Name With Spaces', 'gpg.format': 'ssh', 'gpg.program': '/a path/gpg'}.items():
            value = subprocess.check_output(['git', 'config', '--file', str(self.home / '.gitconfig.local'), '--get', key], text=True).strip()
            self.assertEqual(value, expected)
        self.assertEqual((self.home / '.gitconfig.local').stat().st_mode & 0o777, 0o600)

    def test_preview_reports_difference_without_modifying_files(self):
        original = self.home / '.gitconfig'
        original.write_text('# custom\n')
        original.chmod(0o600)
        result = self.invoke('preview', '--modules', 'git')
        self.assertIn('diff --git', result.stdout)
        self.assertEqual(original.read_text(), '# custom\n')
        self.assertEqual(original.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.state.exists())

    def test_restore_preserves_modes_and_saved_selection(self):
        self.invoke('apply', '--modules', 'git')
        config = self.home / '.gitconfig'
        config.write_text('# original\n')
        config.chmod(0o600)
        self.invoke('apply', '--modules', 'shell')
        self.invoke('backup', '--modules', 'git')
        saved = self.snapshots()[-1]
        config.write_text('# changed\n')
        config.chmod(0o644)
        self.invoke('restore', '--backup', str(saved))
        self.assertEqual(config.read_text(), '# original\n')
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((self.state / 'selection.json').read_text()), ['shell'])
        self.assertGreater(len(self.snapshots()), 3)

    def test_restore_works_with_corrupt_current_selection(self):
        self.invoke('apply', '--modules', 'git')
        saved = self.snapshots()[0]
        (self.state / 'selection.json').write_text('BROKEN')
        self.invoke('restore', '--backup', str(saved))
        self.assertFalse((self.home / '.gitconfig').exists())

    def test_restore_rejects_invalid_manifests_before_writes(self):
        original = self.home / '.gitconfig'
        original.write_text('# keep')
        directory = self.home / 'bad-backup'
        directory.mkdir()
        cases = [None, {}, [{}], [{'path': '../outside', 'existed': False}],
                 [{'path': '.gitconfig', 'existed': 'false'}],
                 [{'path': '.gitconfig', 'existed': False}] * 2]
        for records in cases:
            with self.subTest(records=records):
                (directory / 'manifest.json').write_text(json.dumps(records))
                result = self.invoke('restore', '--backup', str(directory), success=False)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(original.read_text(), '# keep')
                self.assertFalse((self.state / 'backups').exists())

    def test_corrupt_backup_selection_rejected_before_writes(self):
        self.invoke('apply', '--modules', 'git')
        saved = self.snapshots()[0]
        (saved / 'selection.json').write_text('["not-a-module"]')
        original = (self.home / '.gitconfig').read_text()
        self.invoke('restore', '--backup', str(saved), success=False)
        self.assertEqual((self.home / '.gitconfig').read_text(), original)

    def test_restore_requires_directory(self):
        result = self.invoke('restore', success=False)
        self.assertIn('requires --backup', result.stderr)


    def test_restore_originally_absent_paths_that_are_still_absent(self):
        self.invoke('backup', '--modules', 'git')
        original = self.snapshots()[0]
        self.invoke('restore', '--backup', str(original))
        self.assertFalse((self.home / '.gitconfig').exists())
        self.assertFalse((self.home / '.config').exists())

    def test_new_overrides_have_private_permissions(self):
        self.invoke('apply', '--modules', 'shell,git,kitty')
        for path in ('.config/zsh/local.zsh', '.zprofile.local', '.gitconfig.local', '.config/kitty/local.conf'):
            self.assertEqual((self.home / path).stat().st_mode & 0o777, 0o600)
        for directory in self.snapshots():
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)


class PackageTests(unittest.TestCase):
    def capture_install(self, selected, system, env=None):
        calls = []
        def capture(*args, **kwargs):
            record = [str(arg) for arg in args]
            if record[0] == 'brew':
                self.brewfile = Path(record[-1]).read_text()
                self.assertEqual(kwargs['env']['HOMEBREW_NO_AUTO_UPDATE'], '1')
                self.assertEqual(kwargs['env']['HOMEBREW_BUNDLE_NO_UPGRADE'], '1')
            calls.append(record)
        with patch.object(setup, 'run', side_effect=capture), patch.dict(os.environ, env or {}, clear=True):
            setup.install_packages(selected, system)
        return calls

    def test_macos_no_upgrade_and_cask_selection(self):
        calls = self.capture_install(['shell', 'kitty'], 'Darwin')
        self.assertEqual(calls[0][:4], ['brew', 'bundle', 'install', '--no-upgrade'])
        self.assertIn('cask "kitty"', self.brewfile)
        self.assertNotIn('neovim', self.brewfile)
        self.assertEqual(len(calls), 1)

    def test_linux_headless_has_no_desktop_install(self):
        calls = self.capture_install(['shell', 'kitty'], 'Linux')
        self.assertNotIn('cask', self.brewfile)
        self.assertEqual(len(calls), 1)

    def test_linux_wayland_desktop_packages(self):
        calls = self.capture_install(['shell', 'kitty'], 'Linux', {'WAYLAND_DISPLAY': 'wayland-0'})
        self.assertEqual(calls[1], ['sudo', 'apt-get', 'update'])
        self.assertIn('kitty', calls[2])
        self.assertIn('wl-clipboard', calls[2])

    def test_linux_x11_shell_excludes_kitty(self):
        calls = self.capture_install(['shell'], 'Linux', {'DISPLAY': ':1'})
        self.assertIn('xclip', calls[-1])
        self.assertNotIn('kitty', calls[-1])

    def test_package_lists_deduplicated(self):
        formulae, casks = setup.package_plan(['shell', 'shell', 'kitty', 'kitty'], 'Darwin')
        self.assertEqual(len(formulae), len(set(formulae)))
        self.assertEqual(len(casks), len(set(casks)))

    def test_failure_stops_before_desktop_mutations(self):
        with patch.object(setup, 'run', side_effect=subprocess.CalledProcessError(1, 'brew')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.install_packages(['shell', 'kitty'], 'Linux')
            self.assertEqual(run.call_count, 1)


class PluginTests(TemporaryHome):
    def setUp(self):
        super().setUp()
        self.source = self.home / 'source'
        self.source.mkdir()
        self.git('init', '-q', str(self.source))
        self.git('-C', str(self.source), 'config', 'user.name', 'Test')
        self.git('-C', str(self.source), 'config', 'user.email', 'test@example.test')
        (self.source / 'file').write_text('first')
        self.git('-C', str(self.source), 'add', 'file')
        self.git('-C', str(self.source), 'commit', '-qm', 'first')
        self.commit = self.git('-C', str(self.source), 'rev-parse', 'HEAD')
        (self.source / 'file').write_text('second')
        self.git('-C', str(self.source), 'commit', '-qam', 'second')
        self.fixture = self.home / 'fixture'
        self.fixture.mkdir()
        self.lock = [{'module': 'shell', 'path': '.oh-my-zsh', 'url': str(self.source), 'commit': self.commit}]
        self.dest = self.home / '.oh-my-zsh'

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()

    def install(self, selected=None):
        (self.fixture / 'plugins.lock.json').write_text(json.dumps(self.lock))
        with patch.object(setup, 'ROOT', self.fixture):
            setup.install_plugins(selected or ['shell'], self.home)

    def test_clone_uses_locked_commit_not_latest(self):
        self.install()
        self.assertEqual(self.git('-C', str(self.dest), 'rev-parse', 'HEAD'), self.commit)
        self.assertEqual((self.dest / 'file').read_text(), 'first')

    def test_existing_dirty_clone_is_preserved(self):
        self.install()
        (self.dest / 'file').write_text('local edits')
        self.install()
        self.assertEqual((self.dest / 'file').read_text(), 'local edits')

    def test_unselected_plugins_not_installed(self):
        self.install(['git'])
        self.assertFalse(self.dest.exists())

    def test_non_repository_conflict_preserved(self):
        self.dest.mkdir()
        (self.dest / 'keep').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'non-Git'):
            self.install()
        self.assertEqual((self.dest / 'keep').read_text(), 'keep')

    def test_invalid_commit_cleans_partial_checkout(self):
        self.lock[0]['commit'] = '0' * 40
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        self.assertFalse(self.dest.exists())
        self.assertEqual(list(self.home.glob('.dotfiles-plugin-*')), [])


class FontTests(TemporaryHome):
    def setUp(self):
        super().setUp()
        self.fixture = self.home / 'fixture'
        self.fixture.mkdir()
        self.archive = self.fixture / 'font.zip'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('FiraCodeNerdFont-Regular.ttf', b'font fixture')
            archive.writestr('LICENSE', b'license fixture')
            archive.writestr('ignore.sh', b'never execute')
        self.lock = {'firacode': {'url': 'https://example.invalid/font.zip',
                                 'sha256': hashlib.sha256(self.archive.read_bytes()).hexdigest()}}
        self.dest = self.home / '.local/share/fonts/FiraCodeNerdFont'

    def install(self):
        (self.fixture / 'assets.lock.json').write_text(json.dumps(self.lock))
        def download(*args):
            if args[0] == 'curl':
                shutil.copy2(self.archive, args[-1])
        with patch.object(setup, 'ROOT', self.fixture), patch.object(setup, 'run', side_effect=download) as calls:
            setup.install_linux_font(self.home)
        return calls

    def test_valid_archive_filtering_and_second_install_skips_download(self):
        self.install()
        self.assertEqual((self.dest / 'FiraCodeNerdFont-Regular.ttf').read_bytes(), b'font fixture')
        self.assertTrue((self.dest / 'LICENSE').exists())
        self.assertFalse((self.dest / 'ignore.sh').exists())
        self.assertEqual(self.install().call_count, 0)

    def test_wrong_checksum_does_not_install(self):
        self.lock['firacode']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.install()
        self.assertFalse(self.dest.exists())

    def test_missing_font_repaired_even_if_marker_present(self):
        self.install()
        (self.dest / 'FiraCodeNerdFont-Regular.ttf').unlink()
        self.install()
        self.assertTrue((self.dest / 'FiraCodeNerdFont-Regular.ttf').exists())

    def test_invalid_zip_does_not_leave_success_marker(self):
        self.archive.write_bytes(b'not a zip')
        self.lock['firacode']['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaises((ValueError, zipfile.BadZipFile)):
            self.install()
        self.assertFalse((self.dest / '.archive-sha256').exists())

    def rewrite_archive(self, entries):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, content in entries:
                archive.writestr(name, content)
        self.lock['firacode']['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_archive_without_fonts_is_rejected(self):
        self.rewrite_archive([('LICENSE', 'license')])
        with self.assertRaisesRegex(ValueError, 'no fonts'):
            self.install()
        self.assertFalse(self.dest.exists())

    def test_duplicate_basename_is_rejected(self):
        self.rewrite_archive([('a/font.ttf', 'one'), ('b/font.ttf', 'two')])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.install()
        self.assertFalse(self.dest.exists())

    def test_archive_paths_cannot_escape_font_directory(self):
        self.rewrite_archive([('../../outside.ttf', 'font')])
        self.install()
        self.assertEqual((self.dest / 'outside.ttf').read_text(), 'font')
        self.assertFalse((self.home / 'outside.ttf').exists())

    def test_corrupt_installed_font_is_repaired(self):
        self.install()
        (self.dest / 'FiraCodeNerdFont-Regular.ttf').write_bytes(b'corrupt')
        self.install()
        self.assertEqual((self.dest / 'FiraCodeNerdFont-Regular.ttf').read_bytes(), b'font fixture')

    def test_corrupt_installed_manifest_is_repaired(self):
        self.install()
        (self.dest / '.files-sha256.json').write_text('BROKEN')
        self.assertGreater(self.install().call_count, 0)

    def test_network_failure_leaves_no_marker(self):
        (self.fixture / 'assets.lock.json').write_text(json.dumps(self.lock))
        with patch.object(setup, 'ROOT', self.fixture), patch.object(setup, 'run', side_effect=OSError('network failed')):
            with self.assertRaisesRegex(OSError, 'network failed'):
                setup.install_linux_font(self.home)
        self.assertFalse(self.dest.exists())

    def test_font_install_works_without_fontconfig(self):
        with patch.object(setup.shutil, 'which', return_value=None):
            calls = self.install()
        self.assertEqual(calls.call_count, 1)
        self.assertTrue((self.dest / 'FiraCodeNerdFont-Regular.ttf').exists())
