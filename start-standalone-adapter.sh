#!/bin/zsh
set -euo pipefail

python_bin="${ADAPTER_PYTHON:-python3}"
exec "${python_bin}" -m codex_perplexity_adapter.cli --prompt-key "$@"
