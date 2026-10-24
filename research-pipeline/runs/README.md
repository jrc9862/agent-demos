# runs/

| File | Produced by |
|------|-------------|
| `findings.md` | any pipeline run (`python coordinator.py`, `--inject-timeout`, `--compare`) |
| `report_parallel.md`, `latency_parallel.json`, `transcript_parallel.txt` | `python coordinator.py`, `python coordinator.py --compare` |
| `report_timeout.md`, `latency_timeout.json`, `transcript_timeout.txt` | `python coordinator.py --inject-timeout` |
| `report_sequential.md`, `latency_sequential.json`, `transcript_sequential.txt` | `python coordinator.py --compare` |
| `latency.md` | `python coordinator.py --compare` |
| `counter_demo_stripped.txt`, `counter_demo_full.txt` | `python coordinator.py --counter-demo` |
