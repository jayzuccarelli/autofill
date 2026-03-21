#!/usr/bin/env bash
# Install autofill: uv (if needed) + clone + uv sync + add to PATH.
# Remote: curl -fsSL https://cdn.jsdelivr.net/gh/jayzuccarelli/autofill@main/install.sh | bash
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

add_to_path() {
  local bin_dir="$1/bin"
  if echo "$PATH" | tr ':' '\n' | grep -qx "$bin_dir" 2>/dev/null; then
    return 0
  fi
  local shell_rc=""
  if [[ -f "${HOME}/.zshrc" ]]; then
    shell_rc="${HOME}/.zshrc"
  elif [[ -f "${HOME}/.bashrc" ]]; then
    shell_rc="${HOME}/.bashrc"
  fi
  if [[ -n "$shell_rc" ]]; then
    if ! grep -q "autofill/bin" "$shell_rc" 2>/dev/null; then
      printf '\n# autofill\nexport PATH="%s:$PATH"\n' "$bin_dir" >> "$shell_rc"
      echo "Added ${bin_dir} to PATH in ${shell_rc}."
    fi
  fi
  export PATH="${bin_dir}:${PATH}"
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
    uv sync
    add_to_path "$SCRIPT_DIR"
    echo ""
    echo "Installed. Run: autofill"
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
  uv sync
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
  uv sync
fi

add_to_path "$INSTALL_DIR"

echo ""
echo "Installed. Open a new terminal (or run: source ~/.zshrc), then run: autofill"
