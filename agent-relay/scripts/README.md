# Scripts

End-to-end probes run by hand against a live graph (they need FalkorDB and model keys in `.env`). The unit and
integration tests are in `tests/`.

| Script | What it checks |
|---|---|
| `python -m scripts.check_outage` | An outage reaches every affected customer through the graph |
| `python -m scripts.check_sim` | The persona simulator plays its scripted life events through the real agents |
| `python -m scripts.check_sim_noc` | Network Ops warns customers when the simulator fails a node |
| `python -m scripts.replay_kavya` | Replays a recorded intake conversation through the API |
| `python -m scripts.ws_probe <api> <tenant> <seconds>` | Counts live WebSocket events from a running API |
