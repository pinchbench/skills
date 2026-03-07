# Add GitHub Actions for Scheduled Benchmarks

This PR adds automated benchmark runs via GitHub Actions, enabling:

- **Daily scheduled runs** against a configurable set of models
- **Manual triggers** for testing specific models on-demand
- **Parallel execution** via matrix strategy (all models run concurrently)
- **Automatic leaderboard uploads** with results artifacts for debugging

## Files Added

- `.github/workflows/scheduled-benchmarks.yml` - Main workflow
- `Dockerfile.benchmark` - Docker image with OpenClaw pre-installed

## How It Works

1. **Build phase**: Creates/caches a Docker image with OpenClaw + uv installed
2. **Matrix phase**: Parses model list into parallel jobs
3. **Benchmark phase**: Each model runs in its own container
4. **Summary phase**: Aggregates results and posts to PR/run summary

## Required Secrets

Add these to your repository secrets:

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | For Claude models |
| `OPENAI_API_KEY` | For GPT models |
| `GOOGLE_API_KEY` | For Gemini models |
| `OPENROUTER_API_KEY` | For OpenRouter models |
| `PINCHBENCH_TOKEN` | For leaderboard uploads (from `./scripts/run.sh --register`) |

## Usage

### Scheduled Runs
Edit the `DEFAULT_MODELS` env var in the workflow to customize which models run daily.

### Manual Runs
Go to Actions → Scheduled Benchmarks → Run workflow:
- **models**: Comma-separated list (e.g., `anthropic/claude-sonnet-4,openai/gpt-4o`)
- **suite**: `all` or `automated-only`
- **upload**: Whether to push to leaderboard

---

## Self-Hosted Runner Alternative

For longer benchmarks or to avoid GitHub-hosted runner limits (6 hour max), you can use self-hosted runners.

### Why Self-Hosted?

- **No time limits** - GitHub-hosted runners timeout at 6 hours
- **Persistent caching** - Docker images don't need rebuilding
- **Cost control** - No per-minute billing on your own hardware
- **Network locality** - Faster if your OpenClaw instance is local

### Setup

1. **Provision a runner machine** (VM, dedicated server, or even a Raspberry Pi for light loads):
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com | sh
   
   # Install GitHub Actions runner
   # Follow: https://docs.github.com/en/actions/hosting-your-own-runners
   ```

2. **Add the runner to your repo** with labels:
   ```bash
   ./config.sh --url https://github.com/pinchbench/skill \
               --token <TOKEN> \
               --labels self-hosted,benchmark
   ```

3. **Modify the workflow** - change the `runs-on` line:
   ```yaml
   # Before (GitHub-hosted):
   runs-on: ubuntu-latest
   
   # After (self-hosted):
   runs-on: [self-hosted, benchmark]
   ```

4. **Optional: Skip Docker build** - If OpenClaw is installed directly on the runner:
   ```yaml
   benchmark:
     runs-on: [self-hosted, benchmark]
     # Remove the container: block entirely
     steps:
       - uses: actions/checkout@v4
       # ... rest of steps run directly on host
   ```

### Self-Hosted Runner Pool Architecture

For production-grade automation:

```
┌─────────────────────────────────────────────────────────┐
│                    GitHub Actions                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ claude-sonnet│  │   gpt-4o   │  │ gemini-2.5  │     │
│  │    job      │  │    job     │  │    job      │     │
│  └──────┬──────┘  └──────┬─────┘  └──────┬──────┘     │
└─────────┼────────────────┼───────────────┼─────────────┘
          │                │               │
          ▼                ▼               ▼
┌─────────────────────────────────────────────────────────┐
│              Self-Hosted Runner Pool                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Runner 1 │  │ Runner 2 │  │ Runner 3 │   (scale)    │
│  │ (8 CPU)  │  │ (8 CPU)  │  │ (8 CPU)  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│       │              │              │                   │
│       └──────────────┼──────────────┘                   │
│                      ▼                                  │
│            Shared Docker Cache                          │
│         (ghcr.io benchmark-runner)                      │
└─────────────────────────────────────────────────────────┘
```

### Cost Comparison

| Approach | Monthly Cost (6 models × daily) | Limits |
|----------|--------------------------------|--------|
| GitHub-hosted (Linux) | ~$50-100/mo | 6hr max, queuing |
| Self-hosted (1 VM) | ~$20-40/mo | None |
| Self-hosted (spot) | ~$5-15/mo | May be preempted |

### Hybrid Approach

You can mix both! Use GitHub-hosted for quick models, self-hosted for slow ones:

```yaml
jobs:
  benchmark-fast:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        model: [anthropic/claude-sonnet-4, openai/gpt-4o-mini]
    # ...
  
  benchmark-slow:
    runs-on: [self-hosted, benchmark]
    strategy:
      matrix:
        model: [anthropic/claude-opus-4, openai/o3]
    # ...
```

---

## Future Enhancements

- [ ] Slack/Discord notifications on failures
- [ ] Webhook trigger for new model releases
- [ ] Delta benchmarking (only re-run volatile tasks)
- [ ] Result diffing against previous runs
