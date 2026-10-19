#!/usr/bin/env python3
"""Small module installer; chezmoi owns file rendering and copying."""
import argparse
import hashlib
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'modules.json').read_text())
MODULES = MANIFEST['modules']


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def select(names, system):
    result = []
    def add(name):
        if name not in MODULES:
            raise ValueError('Unknown module: ' + name)
        module = MODULES[name]
        if module.get('os', system) != system:
            print('Skipping ' + name + ' on ' + system)
            return
        for dependency in module.get('dependencies', []):
            add(dependency)
        if name not in result:
            result.append(name)
    for name in names:
        add(name)
    return result


def cm(module, home, state, command):
    # Dedicated config prevents interference with an existing chezmoi setup.
    with tempfile.TemporaryDirectory(prefix='dotfiles-chezmoi-') as tmp:
        config = Path(tmp) / 'config.json'
        config.write_text(json.dumps({'sourceDir': str(ROOT / 'modules' / module / 'home'),
                                      'destDir': str(home),
                                      'persistentState': str(state / 'chezmoi.boltdb')}))
        run('chezmoi', '--config', config, '--no-tty', '--force', command)


def targets(selected):
    return list(dict.fromkeys(p for m in selected for p in MODULES[m]['roots']))


def backup(selected, home, state):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory = state / 'backups' / stamp
    directory.mkdir(parents=True, mode=0o700)
    records = []
    for name in targets(selected):
        source = home / name
        exists = source.exists() or source.is_symlink()
        records.append({'path': name, 'existed': exists})
        if exists:
            dest = directory / 'files' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                dest.symlink_to(os.readlink(source))
            elif source.is_dir():
                shutil.copytree(source, dest, symlinks=True)
            else:
                shutil.copy2(source, dest)
    (directory / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')
    selection = state / 'selection.json'
    if selection.exists():
        shutil.copy2(selection, directory / 'selection.json')
    print('Backup:', directory, flush=True)
    return directory


def package_plan(selected, system):
    formulae = ['chezmoi']
    casks = []
    for module in selected:
        formulae += MODULES[module].get('packages', [])
        casks += MODULES[module].get('casks', [])
    if system == 'Linux':
        if 'kitty' in selected:
            print('Linux desktop: kitty via apt; pinned FiraCode Nerd Font archive via assets.lock.json.')
        if 'shell' in selected:
            print('Linux desktop clipboard: install wl-clipboard (Wayland) or xclip (X11), and xdg-utils.')
        casks = []
    return list(dict.fromkeys(formulae)), list(dict.fromkeys(casks))


def install_packages(selected, system):
    formulae, casks = package_plan(selected, system)
    with tempfile.TemporaryDirectory(prefix='dotfiles-packages-') as tmp:
        brewfile = Path(tmp) / 'Brewfile'
        brewfile.write_text(''.join('brew ' + json.dumps(p) + '\n' for p in formulae)
                            + ''.join('cask ' + json.dumps(p) + '\n' for p in casks))
        env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE='1', HOMEBREW_BUNDLE_NO_UPGRADE='1')
        run('brew', 'bundle', 'install', '--no-upgrade', '--file', brewfile, env=env)
    if system == 'Linux' and any(m in selected for m in ('shell', 'kitty')):
        # Desktop packages are optional on headless systems.
        if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
            packages = ['xdg-utils', 'wl-clipboard', 'xclip']
            if 'kitty' in selected:
                packages += ['kitty', 'fontconfig']
            run('sudo', 'apt-get', 'update')
            run('sudo', 'apt-get', 'install', '-y', *packages)



def install_linux_font(home):
    asset = json.loads((ROOT / 'assets.lock.json').read_text())['firacode']
    dest = home / '.local/share/fonts/FiraCodeNerdFont'
    marker = dest / '.archive-sha256'
    if marker.exists() and marker.read_text().strip() == asset['sha256']:
        return
    with tempfile.TemporaryDirectory(prefix='dotfiles-font-') as tmp:
        archive = Path(tmp) / 'font.zip'
        run('curl', '-fsSL', '--max-time', '180', asset['url'], '-o', archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != asset['sha256']:
            raise ValueError('FiraCode font archive checksum mismatch')
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as fonts:
            for entry in fonts.infolist():
                if entry.filename.endswith('.ttf') or Path(entry.filename).name in ('LICENSE', 'OFL.txt'):
                    (dest / Path(entry.filename).name).write_bytes(fonts.read(entry))
        marker.write_text(asset['sha256'] + '\n')
    if shutil.which('fc-cache'):
        run('fc-cache', '-f', dest)


def install_plugins(selected, home):
    for plugin in json.loads((ROOT / 'plugins.lock.json').read_text()):
        if plugin['module'] not in selected:
            continue
        dest = home / plugin['path']
        if dest.exists():
            # Preserve existing clones and any local changes. Doctor reports drift.
            if not (dest / '.git').exists():
                raise ValueError('Existing non-Git plugin directory: ' + str(dest))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.dotfiles-plugin-', dir=dest.parent) as tmp:
            checkout = Path(tmp) / 'checkout'
            run('git', 'clone', '--quiet', plugin['url'], checkout)
            run('git', '-C', checkout, 'checkout', '--quiet', '--detach', plugin['commit'])
            checkout.rename(dest)


def local_overrides(selected, home):
    examples = {
        '.config/zsh/local.zsh': '# Machine-specific settings; never imported into Git.\n# DOTFILES_TMUX_AUTO_ATTACH=0\n# DOTFILES_FASTFETCH=0\n',
        '.zprofile.local': '# Machine-specific SDK paths and login environment.\n',
        '.gitconfig.local': '# Set identity here: git config --file ~/.gitconfig.local user.name "Your Name"\n',
        '.config/kitty/local.conf': '# Optional: background_image ~/Pictures/wallpaper.jpeg\n',
    }
    wanted = []
    if 'shell' in selected:
        wanted += ['.config/zsh/local.zsh', '.zprofile.local']
    if 'git' in selected:
        wanted += ['.gitconfig.local']
    if 'kitty' in selected:
        wanted += ['.config/kitty/local.conf']
    for name in wanted:
        path = home / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        content = examples[name]
        if name == '.gitconfig.local':
            # Preserve the identity of this machine without putting it in the repo.
            for key in ('user.name', 'user.email', 'user.signingkey', 'commit.gpgsign', 'gpg.format', 'gpg.program'):
                old = subprocess.run(['git', 'config', '--file', str(home / '.gitconfig'), '--get', key], capture_output=True, text=True)
                if old.returncode == 0:
                    run('git', 'config', '--file', path, key, old.stdout.strip())
            if path.exists():
                path.chmod(0o600)
                continue
        path.write_text(content)
        path.chmod(0o600)


def doctor(selected, home, state):
    failures = 0
    def check(ok, message):
        nonlocal failures
        print(('OK   ' if ok else 'FAIL ') + message)
        failures += not ok
    for command in dict.fromkeys(['chezmoi'] + [c for m in selected for c in MODULES[m].get('commands', [])]):
        check(bool(shutil.which(command)), command + ' on PATH (rerun install for missing tools)')
    for target in targets(selected):
        check((home / target).exists(), target)
    for plugin in json.loads((ROOT / 'plugins.lock.json').read_text()):
        if plugin['module'] in selected:
            dest = home / plugin['path']
            check((dest / '.git').exists(), plugin['path'] + ' plugin checkout')
            if (dest / '.git').exists():
                head = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
                if head != plugin['commit']:
                    print('NOTE plugin differs from lock:', plugin['path'], '(existing checkout preserved)')
    if 'shell' in selected and shutil.which('zsh'):
        run('zsh', '-n', home / '.zshrc')
    if 'git' in selected:
        identity = subprocess.run(['git', 'config', '--file', str(home / '.gitconfig.local'), '--get', 'user.email'], capture_output=True)
        if identity.returncode:
            print('NOTE set Git identity in ~/.gitconfig.local')
        print('NOTE authenticate separately: gh auth login; verify with gh auth status')
    if 'nvim' in selected:
        print('NOTE editor plugins: nvim --headless "+Lazy! restore" +qa; then :checkhealth')
        print('NOTE Mason/LSP tools, Copilot and Supermaven may need language runtimes or login.')
    if 'kitty' in selected:
        app = Path('/Applications/kitty.app').exists() or shutil.which('kitty')
        check(bool(app), 'kitty application')
        if shutil.which('fc-match'):
            font = subprocess.check_output(['fc-match', 'FiraCode Nerd Font'], text=True).strip()
            check('Fira' in font and 'Nerd' in font, 'FiraCode Nerd Font: ' + font)
        else:
            print('NOTE verify FiraCode Nerd Font in your terminal font picker')
    if 'macos' in selected:
        for app in ('Raycast', 'Karabiner-Elements'):
            check(Path('/Applications', app + '.app').exists(), app + ' application')
        print('NOTE grant Karabiner permissions; import Raycast export separately (see README).')
    print('Backups:', state / 'backups')
    return bool(failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'apply', 'preview', 'doctor', 'backup', 'update', 'packages', 'restore'])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--modules', help='Comma-separated modules; replaces the saved selection')
    group.add_argument('--profile', choices=MANIFEST['profiles'])
    parser.add_argument('--configs-only', action='store_true', help='Apply files without package/plugin installation')
    parser.add_argument('--home', type=Path, default=Path.home(), help='Destination home, also isolates state')
    parser.add_argument('--backup', type=Path, help='Backup directory for restore')
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    state = home / '.local/state/dotfiles'
    saved = state / 'selection.json'
    system = platform.system()
    if system not in ('Darwin', 'Linux'):
        raise ValueError('Supported systems: macOS and Linux')
    if args.profile:
        names = MANIFEST['profiles'][args.profile]
    elif args.modules is not None:
        names = [n.strip() for n in args.modules.split(',') if n.strip()]
        if not names:
            raise ValueError('Select at least one module')
    elif saved.exists():
        names = json.loads(saved.read_text())
    else:
        names = MANIFEST['profiles']['terminal']
    selected = select(names, system)
    print('Modules:', ', '.join(selected), flush=True)
    if args.command == 'preview':
        formulae, casks = package_plan(selected, system)
        print('Homebrew formulae:', ', '.join(formulae))
        print('macOS casks:', ', '.join(casks) or '(none)')
        if shutil.which('brew'):
            installed = set(subprocess.check_output(['brew', 'list', '--formula', '-1'], text=True).splitlines())
            print('Missing formulae:', ', '.join(p for p in formulae if p not in installed) or '(none)')
            if casks:
                installed_casks = set(subprocess.check_output(['brew', 'list', '--cask', '-1'], text=True).splitlines())
                print('Missing casks:', ', '.join(p for p in casks if p not in installed_casks) or '(none)')
        print('Managed paths:\n' + '\n'.join(targets(selected)))
        if shutil.which('chezmoi'):
            # Preview must not touch the destination, including its chezmoi DB.
            with tempfile.TemporaryDirectory(prefix='dotfiles-preview-') as tmp:
                for module in selected:
                    cm(module, home, Path(tmp), 'diff')
        else:
            print('Install chezmoi to see file diffs. No files changed.')
        return 0
    if args.command == 'doctor':
        return doctor(selected, home, state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.command == 'backup':
        backup(selected, home, state)
        return 0
    if args.command == 'restore':
        if not args.backup:
            raise ValueError('restore requires --backup DIRECTORY')
        directory = args.backup.expanduser().resolve()
        records = json.loads((directory / 'manifest.json').read_text())
        # Validate all paths before writing and take a pre-restore snapshot.
        for record in records:
            path = Path(record['path'])
            if path.is_absolute() or '..' in path.parts or record['path'] not in targets(list(MODULES)):
                raise ValueError('Invalid backup path: ' + record['path'])
            source = directory / 'files' / path
            if record['existed'] and not (source.exists() or source.is_symlink()):
                raise ValueError('Missing backup file: ' + str(source))
        restore_modules = [m for m in MODULES if any(r['path'] in MODULES[m]['roots'] for r in records)]
        backup(restore_modules, home, state)
        for record in records:
            dest = home / record['path']
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            elif dest.exists():
                shutil.rmtree(dest)
            if record['existed']:
                source = directory / 'files' / record['path']
                dest.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    dest.symlink_to(os.readlink(source))
                elif source.is_dir():
                    shutil.copytree(source, dest, symlinks=True)
                else:
                    shutil.copy2(source, dest)
        if (directory / 'selection.json').exists():
            shutil.copy2(directory / 'selection.json', saved)
        else:
            saved.unlink(missing_ok=True)
        print('Restored', directory)
        return 0
    if args.command == 'packages':
        install_packages(selected, system)
        return 0
    if args.command == 'update':
        # A config update never upgrades packages or editor plugins.
        run('git', '-C', ROOT, 'pull', '--ff-only')
        # Reload manifests and code from the newly pulled revision.
        forwarded = sys.argv[2:]
        os.execv(sys.executable, [sys.executable, str(ROOT / 'setup.py'), 'install', '--configs-only', *forwarded])
    if not args.configs_only and args.command == 'install':
        install_packages(selected, system)
    if not shutil.which('chezmoi'):
        raise ValueError('chezmoi is required; run ./bootstrap.sh install')
    backup(selected, home, state)
    local_overrides(selected, home)
    if not args.configs_only and args.command == 'install':
        install_plugins(selected, home)
        if system == 'Linux' and 'kitty' in selected:
            install_linux_font(home)
    for module in selected:
        cm(module, home, state, 'apply')
    saved.write_text(json.dumps(selected, indent=2) + '\n')
    if args.command == 'install' and not args.configs_only and 'nvim' in selected:
        data = home / '.local/share/nvim/lazy'
        if not data.exists():
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                       XDG_DATA_HOME=str(home / '.local/share'), XDG_STATE_HOME=str(home / '.local/state'),
                       XDG_CACHE_HOME=str(home / '.cache'))
            run('nvim', '--headless', '+Lazy! restore', '+qa', env=env)
    print('Applied. Run ./setup doctor. Package upgrades and editor plugin updates remain explicit.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, subprocess.CalledProcessError, OSError) as error:
        print('Error:', error, file=sys.stderr)
        sys.exit(1)
