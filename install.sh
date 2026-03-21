#!/usr/bin/env bash
# One command: uv (if needed) + lockfile sync + optional API key save.
# Remote: curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
# Local:  ./install.sh
set -euo pipefail

export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

# Canonical public repo (change only if you fork or rename).
REPO_URL="${REPO_URL:-https://github.com/jayzuccarelli/autofill.git}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/autofill}"
# Where to create a Browser Use API key (printed only; never auto-open the browser).
BROWSER_USE_KEY_URL="${BROWSER_USE_KEY_URL:-https://cloud.browser-use.com/settings?tab=api-keys&new=1}"

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
}

# Optional: save API key to repo .env (600); only when stdin is a TTY.
prompt_api_key() {
  local root="$1"
  if [[ -n "${BROWSER_USE_API_KEY:-}" ]]; then
    return 0
  fi
  if [[ -f "${root}/.env" ]] && grep -q BROWSER_USE_API_KEY "${root}/.env" 2>/dev/null; then
    echo "Using existing ${root}/.env for BROWSER_USE_API_KEY."
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "Visit this page in your browser to create an API key, then add it to ${root}/.env or export BROWSER_USE_API_KEY:"
    echo "  ${BROWSER_USE_KEY_URL}"
    return 0
  fi
  echo ""
  echo "Visit this page to get a Browser Use API key (nothing will open automatically):"
  echo "  ${BROWSER_USE_KEY_URL}"
  echo ""
  read -r -p "Paste your API key here (or press Enter to skip and set it later): " key || true
  if [[ -n "${key:-}" ]]; then
    printf 'export BROWSER_USE_API_KEY=%q\n' "$key" > "${root}/.env"
    chmod 600 "${root}/.env"
    echo "Saved. autofill reads .env when you run it."
  else
    echo "Skipped. Set BROWSER_USE_API_KEY in ${root}/.env or your environment before running autofill."
  fi
}

_script="${BASH_SOURCE[0]:-}"
if [[ -n "$_script" && "$_script" != "-" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$_script")" && pwd)"
  if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    cd "$SCRIPT_DIR"
    install_uv
    if ! command -v uv >/dev/null 2>&1; then
      echo "uv installed but not on PATH. Open a new terminal or add ~/.local/bin to PATH." >&2
      exit 1
    fi
    uv sync
    prompt_api_key "$SCRIPT_DIR"
    echo ""
    echo "Done."
    echo "  1. cp knowledge/profile.example.md knowledge/profile.md  # edit with your details"
    if [[ ! -f "${SCRIPT_DIR}/.env" ]]; then
      echo "  2. Put your key in .env or: export BROWSER_USE_API_KEY=…"
    fi
    echo "  Run: uv run autofill <form-url>   (autofill loads .env from this folder automatically)"
    exit 0
  fi
fi

install_uv
if ! command -v uv >/dev/null 2>&1; then
  echo "uv installed but not on PATH. Open a new terminal or add ~/.local/bin to PATH." >&2
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
  echo "Cloning into ${INSTALL_DIR} …"
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  uv sync
fi

prompt_api_key "$INSTALL_DIR"

echo ""
echo "Done."
echo "  1. cd ${INSTALL_DIR}"
echo "  2. cp knowledge/profile.example.md knowledge/profile.md  # edit with your details"
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  echo "  3. Put your key in .env or: export BROWSER_USE_API_KEY=…"
fi
echo "  Run: uv run autofill <form-url>   (autofill loads .env from this folder automatically)"
