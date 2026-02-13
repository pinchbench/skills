# Agent Guidelines

## Running benchmark.py

Always use `uv` to run the benchmark script:

```
uv run benchmark.py [args...]
```

Do not use `python benchmark.py` directly — `uv run` ensures the correct Python version and dependencies are available.
