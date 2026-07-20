#!/usr/bin/env bash
# Install autofill: uv (if needed) + clone into ~/autofill + uv sync + add to PATH.
# Run with: curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
set -euo pipefail

export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

REPO_URL="${REPO_URL:-https://github.com/jayzuccarelli/autofill.git}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/autofill}"
# Which ref to install. Empty means "newest vN.N.N tag", so a fresh install gets
# a released version rather than whatever happens to be on the default branch.
# Set AUTOFILL_REF=main to track unreleased work.
AUTOFILL_REF="${AUTOFILL_REF:-}"

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
}

link_binary() {
  local project_dir="$1"
  local link_dir="${HOME}/.local/bin"
  mkdir -p "$link_dir"

  # Create a small wrapper that invokes autofill via uv run.
  # --extra chrome-cookies must match the sync below: without it uv prunes the
  # extra back out of the environment on the next run and the Chrome login
  # import silently stops working.
  cat > "$link_dir/autofill" <<WRAPPER
#!/usr/bin/env bash
cd "$project_dir" && exec uv run --extra chrome-cookies autofill "\$@"
WRAPPER
  chmod +x "$link_dir/autofill"

  # Ensure ~/.local/bin is on PATH in the user's shell rc.
  # macOS Terminal.app launches login shells (sources .bash_profile);
  # Linux interactive terminals usually source .bashrc instead.
  local current_shell
  current_shell="$(basename "${SHELL:-/bin/bash}")"
  local rc_files=()
  if [[ "$current_shell" == "zsh" ]]; then
    rc_files=("${HOME}/.zshrc")
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    rc_files=("${HOME}/.bash_profile")
  else
    rc_files=("${HOME}/.bashrc" "${HOME}/.profile")
  fi
  for rc in "${rc_files[@]}"; do
    touch "$rc"
    if ! grep -q '\.local/bin' "$rc" 2>/dev/null; then
      printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
    fi
  done

  # zsh globs '?' in an unquoted URL (its default nomatch) and aborts with
  # "no matches found" before autofill ever runs. 'noglob' disables glob
  # expansion for this command, so `autofill https://x?y=z` works unquoted.
  # (bash passes '?' through literally, so it only needs this on zsh.)
  if [[ "$current_shell" == "zsh" ]]; then
    for rc in "${rc_files[@]}"; do
      if ! grep -q "noglob autofill" "$rc" 2>/dev/null; then
        printf "\nalias autofill='noglob autofill'\n" >> "$rc"
      fi
    done
  fi
}

install_uv
if ! command -v uv >/dev/null 2>&1; then
  echo "uv installed but not on PATH. Open a new terminal and try again." >&2
  exit 1
fi

if [[ -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  cd "$INSTALL_DIR"
  # chrome-cookies pulls browser-cookie3 (LGPL, run only as a subprocess);
  # without the extra the Chrome login import is a silent no-op.
  uv sync --extra chrome-cookies --quiet
elif [[ -d "${INSTALL_DIR}" ]]; then
  echo "INSTALL_DIR exists but is not this project: ${INSTALL_DIR}" >&2
  exit 1
else
  if ! command -v git >/dev/null 2>&1; then
    echo "Install git, or clone the repo manually and run ./install.sh inside it." >&2
    exit 1
  fi
  ref="$AUTOFILL_REF"
  if [[ -z "$ref" ]]; then
    ref="$(git ls-remote --tags --refs --sort=-v:refname "$REPO_URL" 'v*' \
      2>/dev/null | head -1 | sed 's|.*refs/tags/||')"
  fi
  if [[ -n "$ref" ]]; then
    echo "Cloning ${ref} into ${INSTALL_DIR}…"
    # Quiet: cloning a tag otherwise prints a wall of detached-HEAD advice
    # that reads like something went wrong.
    git -c advice.detachedHead=false clone --quiet --branch "$ref" \
      "$REPO_URL" "$INSTALL_DIR"
  else
    # No tags published yet, so fall back to the default branch.
    echo "Cloning into ${INSTALL_DIR}…"
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  fi
  cd "$INSTALL_DIR"
  # chrome-cookies pulls browser-cookie3 (LGPL, run only as a subprocess);
  # without the extra the Chrome login import is a silent no-op.
  uv sync --extra chrome-cookies --quiet
fi

link_binary "$INSTALL_DIR"

echo ""
if [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
  printf '✓ autofill installed.\n\n  Run: \033[1;38;2;120;81;169mautofill\033[0m\n'
else
  printf '✓ autofill installed.\n\n  Run: \033[1;38;2;120;81;169mexec $SHELL && autofill\033[0m\n'
fi
