#!/usr/bin/env bash
# Install autofill: uv (if needed) + clone + uv sync + add to PATH.
# Remote: curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
# Local:  ./install.sh
set -euo pipefail

export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

REPO_URL="${REPO_URL:-https://github.com/jayzuccarelli/autofill.git}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/autofill}"

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
}

link_binary() {
  local target="$1/bin/autofill"
  local link_dir="${HOME}/.local/bin"
  mkdir -p "$link_dir"
  ln -sf "$target" "$link_dir/autofill"

  # Ensure ~/.local/bin is on PATH in the user's shell rc
  local current_shell
  current_shell="$(basename "${SHELL:-/bin/bash}")"
  local rc
  if [[ "$current_shell" == "zsh" ]]; then
    rc="${HOME}/.zshrc"
  else
    rc="${HOME}/.bash_profile"
  fi
  touch "$rc"
  if ! grep -q '\.local/bin' "$rc" 2>/dev/null; then
    printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
  fi
}

# --- Local path (./install.sh from inside a clone) ---
_script="${BASH_SOURCE[0]:-}"
if [[ -n "$_script" && "$_script" != "-" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$_script")" && pwd)"
  if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    cd "$SCRIPT_DIR"
    install_uv
    if ! command -v uv >/dev/null 2>&1; then
      echo "uv installed but not on PATH. Open a new terminal and try again." >&2
      exit 1
    fi
    uv sync --quiet
    link_binary "$SCRIPT_DIR"
    echo ""
    printf '✓ autofill installed.\n\n  Open a new terminal, then run: \033[1;32mautofill\033[0m\n'
    exit 0
  fi
fi

# --- Remote path (curl | bash) ---
install_uv
if ! command -v uv >/dev/null 2>&1; then
  echo "uv installed but not on PATH. Open a new terminal and try again." >&2
  exit 1
fi

if [[ -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  cd "$INSTALL_DIR"
  uv sync --quiet
elif [[ -d "${INSTALL_DIR}" ]]; then
  echo "INSTALL_DIR exists but is not this project: ${INSTALL_DIR}" >&2
  exit 1
else
  if ! command -v git >/dev/null 2>&1; then
    echo "Install git, or clone the repo manually and run ./install.sh inside it." >&2
    exit 1
  fi
  echo "Cloning into ${INSTALL_DIR}…"
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  uv sync --quiet
fi

link_binary "$INSTALL_DIR"

echo ""
printf '✓ autofill installed.\n\n  Open a new terminal, then run: \033[1;32mautofill\033[0m\n'
