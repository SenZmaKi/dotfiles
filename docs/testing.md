# Test plan

Run against disposable homes, local Git fixtures and isolated sockets. Never install
packages into the real machine or change its live configuration during this suite.

| Area | Cases | Evidence |
| --- | --- | --- |
| Selection | profiles, dependencies, duplicates, invalid names, dependency cycles, saved selections, deselection | unit + real CLI |
| Manifest | every managed file covered by backup roots; no credentials/caches/nested repositories; lockfile validity | source checks |
| Apply | each module, both profiles, second run, home with spaces, unrelated files, existing permissions and identity | real chezmoi |
| Preview/doctor | no writes, missing tools, config differences, package/cask differences, plugin drift | CLI + controlled subprocesses |
| Backup/restore | files, directories, modes, symlinks, missing originals, selection, corrupt/malformed input, pre-restore backup | real filesystem + CLI |
| Packages | macOS/Linux, headless/desktop, deduplication, no upgrades, failure propagation | captured installer commands |
| Plugins | pinned commit, existing edits preserved, non-repo conflict, invalid commit cleanup, selected modules only | real local Git repositories |
| Fonts | SHA mismatch, invalid archive, extraction filtering, idempotency, interrupted installation | local ZIP fixtures |
| Shell | minimal dependencies, local overrides, clipboard selection, opener, editor selection, file-manager paths, tmux auto-attach | real Zsh + fake external commands |
| tmux | syntax, prefix, hooks, explicit-command/main exemptions, zoxide target | real isolated tmux server |
| Update | fast-forward from local remote, newly loaded manifests, no package/plugin upgrades, divergence | disposable repository clones |
| Bootstrap | preview passthrough, unsupported OS, prerequisites, installer errors | disposable copy + command fixtures |
| Platforms | macOS execution, Linux container execution | native macOS + disposable Ubuntu container |

Mocked package/desktop commands establish decisions and arguments, not upstream
installer success. Fresh Homebrew bootstrap, full package installation, Neovim
native plugin builds, GUI permissions, Raycast imports and external authentication
remain distinct integration checks. Record actual results below after running.

## Results — 2026-10-19

| Check | Result |
| --- | --- |
| Native macOS, Python 3.14, real chezmoi/Zsh/tmux/Git | **108 passed**, no skips |
| Ubuntu 24.04 ARM64 container, Python 3.12, real chezmoi/Zsh/tmux/Git | **108 passed**, no skips |
| Selection/dependency matrix | All 128 subsets on macOS and Linux (256 cases inside one test) |
| macOS `setup.py` coverage including Python subprocesses | **338/338 statements, 186/186 branches (100%)** |
| ShellCheck | Passed for setup and bootstrap |
| Zsh syntax | Passed for shell startup files and tmux helper |
| actionlint | Passed for GitHub Actions workflow |
| Python compilation | Passed for setup and test sources |
| Live Linux font asset | Downloaded, SHA-256 matched, 18 font files extracted |
| Live upstream plugin Git checkouts | All seven pinned commits fetched and checked out |
| Real upstream shell initialization | Passed in a temporary home with downloaded plugins |

Raw local logs and coverage JSON are under `.local/test-results/` (ignored by Git).
The coverage figure measures `setup.py`, not shell code, external programs, or all
possible device states. Subprocess package installation is captured rather than
performed. Helper executable fixtures verify platform choices and argument handling.
Actual clipboard interaction and macOS application permissions were not exercised.

The Linux suite uses `tests/Dockerfile`; it does not install Homebrew or the full
package set in a blank VM. Real Zsh startup with downloaded upstream plugins is
checked separately by `tests/check_upstream.py` in a disposable home. Native
Neovim plugin builds, external authentication and Raycast settings import remain
outside these results. CI was syntax-checked locally; no remote CI run was dispatched.

## Bugs exposed and corrected

- Restore no longer parses a corrupt current selection before loading the backup.
- Restore rejects malformed record types, duplicate targets and invalid saved
  selections before replacing any files; missing payloads are also rejected.
- Module dependency cycles fail with a descriptive error instead of recursion.
- Font success markers are checked against installed file hashes. Missing or
  damaged files trigger reinstallation; empty/duplicate-basename archives fail.
- `makekey` propagates a failed generator through its pipeline.
- Oh My Zsh's updater is disabled so locked plugin versions stay under explicit
  control.

These changes are tested in temporary homes. The test run does not apply modified
shell configuration to the user's live home or upgrade its packages.

## CI configuration

`.github/workflows/check.yml` runs the full discovered suite on Ubuntu and macOS
with Python 3.12. It runs on pushes, pull requests, or manual dispatch after the
repository is eventually hosted on GitHub. It checks shell syntax and Python
compilation, runs all tests with subprocess coverage, and requires at least 95%
combined statement/branch coverage for `setup.py`. Each OS uploads its test log
and coverage JSON for 14 days, including when a test fails. The jobs have a
15-minute timeout, read-only repository permissions, and run independently so a
failure on one platform does not cancel the other. Superseded workflow runs are
cancelled. There are no deployment or publication steps.

The public GitHub repository is `SenZmaKi/dotfiles`, configured as `origin`.
Pushing `main` triggers the workflow; local results above remain distinct from
GitHub Actions results.
