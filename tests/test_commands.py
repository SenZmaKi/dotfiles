"""CLI entry points, doctor, update and failure ordering."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from test_extended import TemporaryHome
from test_setup import ROOT, setup


class CommandTests(TemporaryHome):
    def call_main(self, *args):
        with patch('sys.argv', ['setup', *args, '--home', str(self.home)]):
            return setup.main()

    def test_configs_only_never_runs_package_or_plugin_installer(self):
        with patch.object(setup, 'install_packages') as packages, patch.object(setup, 'install_plugins') as plugins, patch.object(setup, 'cm'):
            self.call_main('install', '--modules', 'shell', '--configs-only')
            packages.assert_not_called()
            plugins.assert_not_called()

    def test_apply_never_runs_installers(self):
        with patch.object(setup, 'install_packages') as packages, patch.object(setup, 'install_plugins') as plugins, patch.object(setup, 'cm'):
            self.call_main('apply', '--modules', 'shell')
            packages.assert_not_called()
            plugins.assert_not_called()

    def test_package_command_does_not_apply_files_or_change_selection(self):
        with patch.object(setup, 'install_packages') as packages, patch.object(setup, 'cm') as cm:
            self.call_main('packages', '--modules', 'shell')
            packages.assert_called_once()
            cm.assert_not_called()
            self.assertFalse((self.state / 'selection.json').exists())

    def test_failed_package_install_prevents_config_application(self):
        with patch.object(setup, 'install_packages', side_effect=OSError('package failure')), patch.object(setup, 'cm') as cm:
            with self.assertRaisesRegex(OSError, 'package failure'):
                self.call_main('install', '--modules', 'shell')
            cm.assert_not_called()
            self.assertFalse((self.state / 'selection.json').exists())

    def test_failed_apply_keeps_old_selection_and_creates_backup(self):
        self.state.mkdir(parents=True)
        (self.state / 'selection.json').write_text('["git"]')
        with patch.object(setup, 'cm', side_effect=OSError('apply failure')):
            with self.assertRaisesRegex(OSError, 'apply failure'):
                self.call_main('apply', '--modules', 'shell')
        self.assertEqual(json.loads((self.state / 'selection.json').read_text()), ['git'])
        self.assertEqual(len(self.snapshots()), 1)

    def test_preview_without_chezmoi_does_not_write(self):
        with patch.object(setup.shutil, 'which', return_value=None), contextlib.redirect_stdout(io.StringIO()) as output:
            self.call_main('preview', '--modules', 'git')
        self.assertIn('Install chezmoi', output.getvalue())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_doctor_missing_tools_reports_failure_without_writes(self):
        with patch.object(setup.shutil, 'which', return_value=None), contextlib.redirect_stdout(io.StringIO()) as output:
            result = self.call_main('doctor', '--modules', 'git')
        self.assertTrue(result)
        self.assertIn('FAIL gh on PATH', output.getvalue())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_invalid_saved_selection_fails_cleanly(self):
        self.state.mkdir(parents=True)
        for value in ('"shell"', '{}', '[1]', '["invalid"]'):
            (self.state / 'selection.json').write_text(value)
            result = self.invoke('apply', success=False)
            self.assertNotIn('Traceback', result.stderr)
            self.assertFalse((self.state / 'backups').exists())

    def test_unsupported_os_rejected_without_writes(self):
        with patch.object(setup.platform, 'system', return_value='Windows'):
            with self.assertRaisesRegex(ValueError, 'Supported systems'):
                self.call_main('apply')
        self.assertEqual(list(self.home.iterdir()), [])

    def test_editor_plugins_only_restored_for_new_install(self):
        with patch.object(setup, 'install_packages'), patch.object(setup, 'install_plugins'), patch.object(setup, 'cm'), patch.object(setup, 'run') as run:
            self.call_main('install', '--modules', 'nvim')
            self.assertEqual(run.call_args.args, ('nvim', '--headless', '+Lazy! restore', '+qa'))
            self.assertEqual(run.call_args.kwargs['env']['HOME'], str(self.home.resolve()))
            run.reset_mock()
            (self.home / '.local/share/nvim/lazy').mkdir(parents=True)
            self.call_main('install', '--modules', 'nvim')
            run.assert_not_called()

    def test_bootstrap_preview_is_read_only(self):
        result = subprocess.run([str(ROOT / 'bootstrap.sh'), 'preview', '--modules', 'git', '--home', str(self.home)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_chezmoi_reports_install_instruction(self):
        with patch.object(setup.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'chezmoi is required'):
                self.call_main('apply', '--modules', 'shell')
        self.assertFalse((self.state / 'backups').exists())

    def test_linux_full_install_runs_font_installer(self):
        with patch.object(setup.platform, 'system', return_value='Linux'), patch.object(setup, 'install_packages'), patch.object(setup, 'install_plugins'), patch.object(setup, 'cm'), patch.object(setup, 'install_linux_font') as font:
            self.call_main('install', '--modules', 'kitty')
            font.assert_called_once_with(self.home.resolve())

    def test_update_reexecutes_config_only_with_original_arguments(self):
        class Reexec(Exception):
            pass
        with patch.object(setup, 'run') as run, patch.object(setup.os, 'execv', side_effect=Reexec) as reexec:
            with self.assertRaises(Reexec):
                self.call_main('update', '--modules', 'git')
            self.assertEqual(run.call_args.args[-2:], ('pull', '--ff-only'))
            args = reexec.call_args.args[1]
            self.assertIn('--configs-only', args)
            self.assertEqual(args[2:5], ['install', '--configs-only', '--modules'])

    def test_preview_lists_missing_desktop_casks(self):
        with patch.object(setup.platform, 'system', return_value='Darwin'), patch.object(setup.shutil, 'which', side_effect=lambda name: '/mock/brew' if name == 'brew' else None), patch.object(setup.subprocess, 'check_output', return_value=''), contextlib.redirect_stdout(io.StringIO()) as output:
            self.call_main('preview', '--modules', 'kitty')
        self.assertIn('Missing casks: kitty, font-fira-code-nerd-font', output.getvalue())
        self.assertEqual(list(self.home.iterdir()), [])


@unittest.skipUnless(shutil.which('chezmoi'), 'requires chezmoi')
class UpdateTests(TemporaryHome):
    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()

    def setUp(self):
        super().setUp()
        self.repo = self.home / 'repo'
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.git('init', '-q', '-b', 'main', str(self.repo))
        self.git('-C', str(self.repo), 'config', 'user.name', 'Test')
        self.git('-C', str(self.repo), 'config', 'user.email', 'test@example.test')
        self.git('-C', str(self.repo), 'add', '.')
        self.git('-C', str(self.repo), 'commit', '-qm', 'initial')
        self.remote = self.home / 'remote.git'
        self.git('clone', '-q', '--bare', str(self.repo), str(self.remote))
        self.git('-C', str(self.repo), 'remote', 'add', 'origin', str(self.remote))
        self.git('-C', str(self.repo), 'fetch', '-q', 'origin')
        self.git('-C', str(self.repo), 'branch', '--set-upstream-to', 'origin/main')
        self.writer = self.home / 'writer'
        self.git('clone', '-q', str(self.remote), str(self.writer))
        self.git('-C', str(self.writer), 'config', 'user.name', 'Test')
        self.git('-C', str(self.writer), 'config', 'user.email', 'test@example.test')
        self.dest = self.home / 'destination'
        self.dest.mkdir()

    def publish(self):
        self.git('-C', str(self.writer), 'add', '.')
        self.git('-C', str(self.writer), 'commit', '-qm', 'upstream change')
        self.git('-C', str(self.writer), 'push', '-q')

    def test_fast_forward_reloads_manifest_and_applies_new_module(self):
        manifest = self.writer / 'modules.json'
        data = json.loads(manifest.read_text())
        data['modules']['fresh'] = {'roots': ['.fresh'], 'packages': ['must-not-install']}
        manifest.write_text(json.dumps(data))
        source = self.writer / 'modules/fresh/home'
        source.mkdir(parents=True)
        (source / 'dot_fresh').write_text('new module')
        data['profiles']['terminal'] = ['fresh']
        manifest.write_text(json.dumps(data))
        self.publish()
        result = subprocess.run([str(self.repo / 'setup'), 'update', '--home', str(self.dest)], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.dest / '.fresh').read_text(), 'new module')
        self.assertEqual(json.loads((self.dest / '.local/state/dotfiles/selection.json').read_text()), ['fresh'])

    def test_diverged_history_fails_without_config_changes(self):
        (self.writer / 'upstream').write_text('remote')
        self.publish()
        (self.repo / 'local').write_text('local')
        self.git('-C', str(self.repo), 'add', 'local')
        self.git('-C', str(self.repo), 'commit', '-qm', 'local')
        result = subprocess.run([str(self.repo / 'setup'), 'update', '--modules', 'git', '--home', str(self.dest)], capture_output=True, text=True, timeout=40)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.dest / '.gitconfig').exists())


class BootstrapTests(TemporaryHome):
    def setUp(self):
        super().setUp()
        self.fixture = self.home / 'fixture'
        self.fixture.mkdir()
        shutil.copy2(ROOT / 'bootstrap.sh', self.fixture / 'bootstrap.sh')
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.log = self.home / 'log'
        self.write_tool(self.fixture / 'setup', 'printf "%s\\n" "$@" > "$TEST_LOG"; exit "${STUB_EXIT:-0}"')
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], TEST_LOG=str(self.log))

    def write_tool(self, path, body):
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def invoke_bootstrap(self, *args):
        return subprocess.run([str(self.fixture / 'bootstrap.sh'), *args], capture_output=True, text=True, env=self.env, timeout=20)

    def test_preview_does_not_check_or_install_prerequisites(self):
        self.write_tool(self.bin / 'uname', 'exit 91')
        result = self.invoke_bootstrap('preview', '--modules', 'git')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'preview\n--modules\ngit\n')

    def test_unsupported_system_stops_before_setup(self):
        self.write_tool(self.bin / 'uname', 'printf OpenBSD')
        result = self.invoke_bootstrap('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Supported systems', result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_command_line_tools_requests_install_and_stops(self):
        self.write_tool(self.bin / 'uname', 'printf Darwin')
        self.write_tool(self.bin / 'xcode-select', '[ "$1" = --install ] && printf REQUESTED > "$TEST_LOG"')
        result = self.invoke_bootstrap('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.log.read_text(), 'REQUESTED')
        self.assertIn('rerun', result.stdout)

    def test_setup_exit_status_and_arguments_preserved(self):
        self.env['STUB_EXIT'] = '43'
        result = self.invoke_bootstrap('doctor', '--modules', 'shell,git')
        self.assertEqual(result.returncode, 43)
        self.assertEqual(self.log.read_text(), 'doctor\n--modules\nshell,git\n')

    def test_no_arguments_default_to_install(self):
        self.write_tool(self.bin / 'uname', 'printf OpenBSD')
        result = self.invoke_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Supported systems', result.stderr)

    def test_linux_prerequisites_use_sudo_only_on_debian(self):
        self.write_tool(self.bin / 'uname', 'printf Linux')
        self.write_tool(self.bin / 'brew', 'exit 0')
        self.write_tool(self.bin / 'sudo', 'printf "%s\\n" "$*" >> "$TEST_LOG.apt"')
        result = self.invoke_bootstrap('install', '--modules', 'git')
        if Path('/etc/debian_version').exists():
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('apt-get update', Path(str(self.log) + '.apt').read_text())
            self.assertIn('python3', Path(str(self.log) + '.apt').read_text())
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Ubuntu/Debian', result.stderr)
            self.assertFalse(Path(str(self.log) + '.apt').exists())


class DoctorTests(TemporaryHome):
    def doctor(self, selected, which=None, output=''):
        with patch.object(setup.shutil, 'which', side_effect=which or (lambda name: '/mock/' + name)), patch.object(setup.subprocess, 'check_output', return_value=output), patch.object(setup, 'run'), contextlib.redirect_stdout(io.StringIO()) as captured:
            result = setup.doctor(selected, self.home, self.state)
        return result, captured.getvalue()

    def test_missing_shell_plugins_are_reported(self):
        result, output = self.doctor(['shell'])
        self.assertTrue(result)
        self.assertIn('plugin checkout', output)
        self.assertIn('FAIL', output)

    def test_plugin_drift_is_reported_without_resetting(self):
        for plugin in json.loads((ROOT / 'plugins.lock.json').read_text()):
            if plugin['module'] == 'shell':
                (self.home / plugin['path'] / '.git').mkdir(parents=True)
        _, output = self.doctor(['shell'], output='different-commit')
        self.assertIn('differs from lock', output)
        self.assertIn('existing checkout preserved', output)

    def test_neovim_follow_up_requirements_are_reported(self):
        _, output = self.doctor(['nvim'])
        self.assertIn('Lazy! restore', output)
        self.assertIn('Mason/LSP', output)

    def test_font_mismatch_is_a_failure(self):
        result, output = self.doctor(['kitty'], output='Fallback.ttf: Sans Regular')
        self.assertTrue(result)
        self.assertIn('FAIL FiraCode Nerd Font', output)

    def test_font_without_fontconfig_has_manual_check(self):
        _, output = self.doctor(['kitty'], which=lambda name: None if name == 'fc-match' else '/mock/' + name)
        self.assertIn('verify FiraCode Nerd Font', output)

    def test_desktop_permission_follow_up_is_reported(self):
        _, output = self.doctor(['macos'])
        self.assertIn('grant Karabiner permissions', output)

    def test_git_doctor_succeeds_with_tools_paths_and_identity(self):
        for path in setup.targets(['git']):
            dest = self.home / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text('')
        subprocess.run(['git', 'config', '--file', str(self.home / '.gitconfig.local'), 'user.email', 'test@example.test'], check=True)
        result, output = self.doctor(['git'])
        self.assertFalse(result, output)
        self.assertNotIn('FAIL', output)

    def test_matching_plugin_lock_has_no_drift_note(self):
        fixture = self.home / 'fixture'
        fixture.mkdir()
        lock = [{'module': 'shell', 'path': '.oh-my-zsh', 'commit': 'matching'}]
        (fixture / 'plugins.lock.json').write_text(json.dumps(lock))
        (self.home / '.oh-my-zsh/.git').mkdir(parents=True)
        with patch.object(setup, 'ROOT', fixture):
            _, output = self.doctor(['shell'], output='matching')
        self.assertNotIn('differs from lock', output)
