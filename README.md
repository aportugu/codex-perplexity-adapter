# Codex–Perplexity Adapter

A local compatibility service that lets the Codex CLI and IDE integrations use models exposed by Perplexity's Agent API. It implements the OpenAI-compatible Responses endpoints Codex needs and translates custom tools, namespaced tools, tool-call history, structured tool output, and streamed SSE events.

LiteLLM is not required, no installed package is patched, and your Perplexity API key remains in the local adapter process.

```text
Codex CLI or IDE extension
        │  OpenAI Responses API
        ▼
Codex–Perplexity Adapter on 127.0.0.1:4000
        │  translated Responses API
        ▼
Perplexity Agent API
```

## Download

The easiest option on macOS is a ready-to-run app from the [latest release](https://github.com/aportugu/codex-perplexity-adapter/releases/latest):

| Mac | Download |
| --- | --- |
| Apple Silicon (M1 or newer) | [Codex-Perplexity-Adapter-macOS-arm64.zip](https://github.com/aportugu/codex-perplexity-adapter/releases/latest/download/Codex-Perplexity-Adapter-macOS-arm64.zip) |
| Intel | [Codex-Perplexity-Adapter-macOS-x86_64.zip](https://github.com/aportugu/codex-perplexity-adapter/releases/latest/download/Codex-Perplexity-Adapter-macOS-x86_64.zip) |

Both apps require macOS 13 or newer and include Python and all dependencies. No system-wide Python, pipx, or LiteLLM installation is needed.

After unzipping, move **Codex Perplexity Adapter.app** to Applications. Open it, enter your Perplexity API key, and choose **Start Adapter**. Keep the app open while using Codex; closing it stops the service. Logs are written to `~/Library/Logs/Codex Perplexity Adapter.log`.

The apps are ad-hoc signed but not Apple-notarized. On first launch, macOS may require you to right-click the app, choose **Open**, and confirm.

## Requirements

- A [Perplexity API key](https://www.perplexity.ai/settings/api)
- Codex CLI or a compatible IDE integration
- For source installs: Python 3.10 or newer

## Install from source

Clone and install the project in an isolated environment:

```sh
git clone https://github.com/aportugu/codex-perplexity-adapter.git
cd codex-perplexity-adapter
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/codex-perplexity-adapter --prompt-key
```

The prompt does not echo or save the Perplexity API key. Leave the terminal running while using Codex.

Alternatively, install the wheel from the [latest release](https://github.com/aportugu/codex-perplexity-adapter/releases/latest) with pipx:

```sh
pipx install codex_perplexity_adapter-0.1.1-py3-none-any.whl
codex-perplexity-adapter --prompt-key
```

## Configure Codex

Copy the provider and profile from [`perplexity.config.toml`](perplexity.config.toml) into `~/.codex/config.toml`, then select the `perplexity` profile. The important settings are:

```toml
[model_providers.perplexity_adapter]
name = "Perplexity Adapter"
base_url = "http://127.0.0.1:4000/v1"
wire_api = "responses"
experimental_bearer_token = "local-adapter-token"

[profiles.perplexity]
model = "gpt-5.6-sol"
model_provider = "perplexity_adapter"
model_reasoning_effort = "medium"
```

Start Codex with:

```sh
codex --profile perplexity
```

The included `codex-perplexity` launcher provides the same behavior on systems where Codex is bundled with the ChatGPT macOS app.

## Docker

```sh
docker build -t codex-perplexity-adapter .
docker run --rm -it \
  -p 127.0.0.1:4000:4000 \
  codex-perplexity-adapter \
  codex-perplexity-adapter --host 0.0.0.0 --prompt-key
```

## Command-line options

```text
--host HOST                 Listening host (default: 127.0.0.1)
--port PORT                 Listening port (default: 4000)
--model-alias MODEL         Model name exposed to Codex
--upstream-model MODEL      Model sent to Perplexity
--upstream-url URL          Perplexity Responses endpoint
--local-token TOKEN         Bearer token expected from Codex
--prompt-key                Securely prompt for the Perplexity API key
```

Instead of `--prompt-key`, set `PERPLEXITY_API_KEY` in the adapter process. `ADAPTER_LOCAL_TOKEN` can override the local bearer token; update the Codex configuration to match.

## API endpoints

- `POST /v1/responses` — translating proxy used by Codex
- `GET /v1/models` — exposes the configured model alias
- `GET /health` — local liveness check that does not spend API credits

## Development

Run the test suite without contacting Perplexity:

```sh
python3 -m unittest discover -s tests -v
```

The tests cover custom-tool round trips, structured IDE tool output, non-streaming responses, incremental streaming, and streamed tool calls.

To build the Apple Silicon app:

```sh
./build-macos-app.sh
```

To build the Intel app on an Apple Silicon Mac with Rosetta installed:

```sh
./build-macos-intel.sh
```

The Intel build downloads a pinned, checksum-verified x86_64 Python runtime under `build/toolchains`; it does not install an Intel runtime system-wide.

The older LiteLLM patch remains in `perplexity_responses_transformation.py` for reference. New installations should use the standalone adapter.

## Security

The service listens only on `127.0.0.1` by default. Do not expose it publicly or commit API keys. The adapter sends the Perplexity key only in the upstream `Authorization` header.

## License and project status

Released under the [MIT License](LICENSE).

This is an independent, unofficial project. It is not affiliated with, endorsed by, or sponsored by OpenAI or Perplexity. Codex, OpenAI, Perplexity, and related marks belong to their respective owners.
