# Codex–Perplexity Adapter

A local service that lets the Codex CLI and compatible IDE integrations use models exposed by Perplexity's Agent API. It translates the OpenAI Responses API traffic produced by Codex into the format accepted by Perplexity.

```text
Codex CLI or IDE extension
        │
        ▼
Local adapter on 127.0.0.1:4000
        │  HTTPS
        ▼
Perplexity Agent API
```

## Download and setup

Download the appropriate macOS app from the [latest release](https://github.com/aportugu/codex-perplexity-adapter/releases/latest):

| Mac | Download |
| --- | --- |
| Apple Silicon (M1 or newer) | [Codex-Perplexity-Adapter-macOS-arm64.zip](https://github.com/aportugu/codex-perplexity-adapter/releases/latest/download/Codex-Perplexity-Adapter-macOS-arm64.zip) |
| Intel | [Codex-Perplexity-Adapter-macOS-x86_64.zip](https://github.com/aportugu/codex-perplexity-adapter/releases/latest/download/Codex-Perplexity-Adapter-macOS-x86_64.zip) |

The apps require macOS 13 or newer. After unzipping, move **Codex Perplexity Adapter.app** to Applications, open it, enter a Perplexity API key, and choose **Start Adapter**. Keep the app open while using Codex.

The apps are ad-hoc signed but not Apple-notarized. On first launch, macOS may require you to right-click the app, choose **Open**, and confirm.

## Configure Codex

Copy the contents of [`perplexity.config.toml`](perplexity.config.toml) into `~/.codex/config.toml`, then run:

```sh
codex --profile perplexity
```

The adapter must remain running while the profile is in use.

## Data handling and governance

- **Data processed:** Requests may contain prompts, instructions, conversation context, tool definitions, tool calls, and tool results supplied by Codex.
- **External destination:** The adapter transforms this data and sends it over HTTPS to the Perplexity Agent API. The adapter itself contains no analytics or telemetry integrations.
- **Credentials:** The Perplexity API key is held in the adapter process, sent only to Perplexity in the upstream authorization header, and is not saved by the application. The local bearer token authenticates communication between Codex and the adapter.
- **Storage and logs:** The adapter has no database and does not intentionally persist request or response bodies. The macOS app writes operational and access logs to `~/Library/Logs/Codex Perplexity Adapter.log`.
- **Network boundary:** The service listens on `127.0.0.1` by default and is not intended to be exposed to a network.
- **Organizational responsibility:** Users should submit only data approved for processing by Perplexity under their organization's policies, agreements, and configured retention controls. This adapter does not alter Perplexity's processing or retention practices.

## License and project status

Released under the [MIT License](LICENSE).

This is an independent, unofficial project. It is not affiliated with, endorsed by, or sponsored by OpenAI or Perplexity. Codex, OpenAI, Perplexity, and related marks belong to their respective owners.
