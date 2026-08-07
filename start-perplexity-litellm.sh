#!/bin/zsh
set -euo pipefail

config_path="${HOME}/.codex/litellm/perplexity.yaml"
log_path="${HOME}/.codex/litellm/perplexity.log"

if [[ "${1:-}" == "--prompt-key" ]]; then
  read -rs "PERPLEXITY_API_KEY?Perplexity API key: "
  print
  export PERPLEXITY_API_KEY
  shift
fi

if [[ -z "${PERPLEXITY_API_KEY:-}" ]]; then
  print -u2 "PERPLEXITY_API_KEY is not set. Rerun with --prompt-key."
  exit 1
fi

exec "${HOME}/.local/bin/litellm" \
  --config "${config_path}" \
  --host 127.0.0.1 \
  --port 4000 \
  >>"${log_path}" 2>&1
