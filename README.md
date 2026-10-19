# Dotfiles

A modular terminal and desktop environment for macOS and Ubuntu/Debian Linux.
Git stores configuration and dependency manifests. Homebrew installs CLI packages,
macOS casks install desktop tools, and chezmoi applies each selected module's files.
Python's standard library coordinates selection, backups, and diagnostics.

## New machine

Clone the private repository using an authenticated GitHub CLI, then:

```sh
gh repo clone SenZmaKi/dotfiles
cd dotfiles
./bootstrap.sh install --profile terminal
# Or choose exactly what you need:
./bootstrap.sh install --modules shell,nvim,git
# Desktop machine:
./bootstrap.sh install --profile workstation
```

Bootstrap installs prerequisites and Homebrew when needed. On macOS, finish the
Command Line Tools installer and rerun if prompted. On Linux, sudo is required
for apt prerequisites; do not run the whole setup as root. Linux bootstrap supports
Ubuntu/Debian. macOS supports Intel and Apple Silicon through Homebrew's prefixes.
Homebrew's own OS/architecture requirements still apply.

The private remote is `https://github.com/SenZmaKi/dotfiles`. Authenticate with
`gh auth login` before cloning on subsequent devices. Logins, SSH keys, application permissions, and project
repositories are separate. This is an environment installer, not a disk backup.

## Modules

| Module | Contents |
| --- | --- |
| `shell` | Zsh, Oh My Zsh and pinned plugins, Oh My Posh and saved theme, zoxide, fzf, bat, lf, fastfetch |
| `tmux` | tmux, pinned TPM and gpakosz/.tmux, bindings, session/zoxide helper; includes `shell` |
| `nvim` | Your Neovim/LazyVim config and plugin lockfile, ripgrep, fd, tree-sitter, Node, Yarn |
| `git` | Git, gh, delta, shared Git settings and global ignore; excludes auth and identity |
| `monitoring` | btop and its settings |
| `kitty` | kitty, FiraCode Nerd Font and terminal settings |
| `macos` | Karabiner configuration and application, Raycast application |

`terminal` selects shell, tmux, nvim, git, monitoring. `workstation` adds kitty and
macos. macos is skipped on Linux. Dependencies are deduplicated. `--modules` and
`--profile` replace the saved selection, rather than adding to it. Later commands
reuse the selection saved in `~/.local/state/dotfiles/selection.json`.
Deselecting a module leaves its existing files/packages intact; removal is manual.
Mise, SDKs, databases, AI CLIs, and deployment tools are deliberately outside scope.

On a Linux desktop, apt installs kitty, xdg-utils, wl-clipboard and xclip when
DISPLAY or WAYLAND_DISPLAY is set. On a headless system, select `terminal` or
individual modules; desktop helpers fail with an explanation when unavailable.

## Everyday commands

```sh
./setup preview                     # read-only packages, paths and file diffs
./setup apply                       # back up and apply configuration only
./setup doctor                      # check tools, configuration, plugins and prerequisites
./setup backup                      # snapshot selected managed paths
./setup update                      # git pull --ff-only, then back up and apply; no upgrades
./setup packages                    # install missing selected packages without upgrading
./setup install --modules shell,git # install packages/plugins and apply this selection
```

Edit files under `modules/<name>/home/`, review with `./setup preview`, then run
`./setup apply`. Commit changes in this repository explicitly. If you edit a live
configuration file directly, copy that change back to the corresponding source
before applying again; `preview` shows the difference. These module sources use
chezmoi's `dot_`, `private_`, and `symlink_` filename attributes.

Package versions follow Homebrew availability; package installation uses
`--no-upgrade`, and configuration updates never update packages or editor plugins.
Upgrade a package deliberately with `brew upgrade <package>`. Shell/tmux plugin
commits are in `plugins.lock.json`; setup preserves existing clones rather than
resetting local changes. To change plugin versions, update the lock and the clone
explicitly. Doctor notes commit drift. TPM's own plugin update keybindings remain
available and can also cause drift from the lock.

## Local settings and identity

These files are created when needed and never imported into the repository:

- `~/.config/zsh/local.zsh`: aliases and interactive overrides. Set
  `DOTFILES_TMUX_AUTO_ATTACH=0` or `DOTFILES_FASTFETCH=0` to disable those features.
- `~/.zprofile.local`: machine-specific login environment and SDK paths.
- `~/.zshenv.local`: optional minimal non-interactive environment.
- `~/.gitconfig.local`: identity, signing, and work-specific includes. Existing
  direct user.name/email/signing settings are copied here during initial migration.
- `~/.config/kitty/local.conf`: optional wallpaper or machine-specific appearance.

```sh
git config --file ~/.gitconfig.local user.name "Your Name"
git config --file ~/.gitconfig.local user.email "you@example.com"
gh auth login
```

To make Zsh your login shell, add the installed Zsh path to `/etc/shells` if absent,
then run `chsh -s "$(command -v zsh)"`. Setup does not change your login shell.
Open a new login shell after applying; running shells and tmux servers retain their
existing environment until restarted/reloaded.

## Neovim

The imported configuration enables language and AI extras. Node and Yarn are
included because Markdown preview and editor tooling need them; full SDKs and
language environments remain your choice. A C compiler is checked by doctor
(Command Line Tools on macOS, build-essential from Linux bootstrap).

Full installation restores editor plugins when no existing Lazy plugin directory
is present. For an existing installation, restore committed plugin versions explicitly:

```sh
nvim --headless '+Lazy! restore' +qa
```

Then run `:checkhealth`. Mason can install additional LSPs, formatters and linters;
those may need runtimes not installed by this repository. Copilot/Supermaven need
separate authentication. The Neovim lockfile was copied with your local edits;
the original Neovim repository and its metadata are not changed by setup.

## Desktop settings

Kitty uses FiraCode Nerd Font. Wallpaper paths are local overrides because the
image is not bundled. macOS installs the font through Homebrew Cask. Linux downloads Nerd Fonts v3.4.0,
verifies the SHA-256 in `assets.lock.json`, and installs it under
`~/.local/share/fonts/FiraCodeNerdFont/`.

Karabiner rules are versioned, but macOS still requires approving its permissions.
Raycast's internal extension/cache directory is not a portable settings export.
On the old machine use Raycast's **Export Settings & Data** command; keep the
`.rayconfig` export in private storage, then use **Import Settings & Data** on the
new machine. Exports are ignored by Git because they can contain private data.
Raycast settings are not automatically restored by setup.

## Backups and restore

Before each apply, setup copies selected managed paths to a timestamped directory
under `~/.local/state/dotfiles/backups/`, including symlinks, existing Neovim Git
metadata, and a manifest recording paths that did not exist. Backups may contain
private machine configuration: keep them outside Git. No automatic pruning occurs.

```sh
./setup restore --backup ~/.local/state/dotfiles/backups/TIMESTAMP
```

Restore first snapshots the current affected paths, then restores the selected
backup (including removing paths that were originally absent). Newly created
local overrides and installed packages/plugin repositories remain in place.
Backups are printed during apply; a failed apply can leave some files applied,
so use restore rather than assuming all writes were rolled back.

## Validation

```sh
shellcheck setup bootstrap.sh
python3 -m unittest discover -s tests -v
```

Tests run real chezmoi against temporary homes, including idempotency, module
isolation, auth-file preservation, identity migration, corrupt-backup rejection,
symlink/directory recovery, and shell startup without optional dependencies.
GitHub Actions runs these on macOS/Linux when this repository is pushed.
They do not prove fresh-machine package installation, GUI permissions, AI login,
or native Neovim plugin builds. Doctor reports separate follow-up checks.

## Extending

Add a module entry to `modules.json` with packages/casks, required commands, optional
dependencies/OS, and managed backup roots. Put its chezmoi source in
`modules/<name>/home/`. Every managed target must be covered by a backup root.
There are no automatic delete rules or scripts executed from imported configs.

References: [chezmoi](https://www.chezmoi.io/),
[Homebrew Bundle](https://docs.brew.sh/Brew-Bundle-and-Brewfile).
The saved cloud-context theme comes from
[Oh My Posh](https://github.com/JanDeDobbeleer/oh-my-posh) (MIT).

## Comprehensive regression suite

The [test matrix and recorded results](docs/testing.md) describe each evidence layer.
The suite includes real chezmoi application/recovery, all 128 module selections on
both platforms, real local Git clones/updates, real Zsh and isolated tmux sessions.
Package-manager commands and clipboard/desktop helpers use controlled fixtures.

```sh
python3 -m unittest discover -s tests -v

# Reproduce Ubuntu 24.04 checks without changing your host:
docker build -f tests/Dockerfile -t dotfiles-tests:local .
docker run --rm -v "$PWD:/work:ro" dotfiles-tests:local

# Optional coverage, including Python subprocesses:
uv run --with 'coverage>=7.10' coverage erase
uv run --with 'coverage>=7.10' coverage run -m unittest discover -s tests -v
uv run --with 'coverage>=7.10' coverage combine
uv run --with 'coverage>=7.10' coverage report

# Optional live GitHub downloads; uses a temporary home:
python3 tests/check_upstream.py
```

Restore validates backup record types, duplicate paths, payload existence and saved
module selection before replacing files. A corrupt current selection does not block
recovery. Linux font installation verifies the downloaded archive and installed file
hashes, so deleted/corrupt fonts are repaired rather than hidden by a success marker.
Oh My Zsh automatic updates are disabled; plugin changes remain explicit.
