# Dotfiles maintenance

- Keep modules optional. Add every managed path to its module's backup roots.
- Never import authentication, histories, caches, installed dependencies or local overrides.
- Preserve existing plugin clones and Neovim's separate Git metadata.
- Configuration updates must not upgrade packages or editor plugins.
- Run `shellcheck setup bootstrap.sh` and `python3 -m unittest discover -s tests -v`.
- Verify changes in temporary homes before applying to the real home.
- Do not inspect browser features unless explicitly asked.
