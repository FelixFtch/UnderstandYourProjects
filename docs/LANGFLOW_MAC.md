# Real Langflow canvas on Mac

UnderstandYourProjects uses Langflow as a real visual canvas for the Jarvis
flow. The custom nodes are maintained in the HomeHub repository because
HomeHub owns the agent-runtime flow contract:

```text
/Users/felixfang/projects/jarvis-homehub/jetson/services/agent-runtime/
  langflow_components/components/   # one Langflow component per file
  langflow_components/examples/      # pre-wired studio.flow and voice.flow
```

The canvas is a view and replay surface. The Jetson HomeHub agent-runtime is
still the only flow executor. Langflow does not become an identity, policy,
grant, revocation, audit, or project-file authority; those boundaries remain
with HomeHub and UnderstandYourProjects respectively.

For the block-by-block explanation of the Studio and Voice canvases, including
the Turn bundle, node slicing, execution order, and authority boundaries, see
the canonical [HomeHub LangFlow flow guide](https://github.com/FelixFtch/jarvis-homehub/blob/main/docs/architecture/LANGFLOW_FLOW_GUIDE.md).

## Start it

Docker Desktop must be running. The launcher creates an SSH tunnel using the
existing `jetson-us-cf` entry in `~/.ssh/config`, then binds the Langflow UI to
Mac loopback only. Set a local Langflow login password in the shell:

```bash
cd /Users/felixfang/Documents/ChatGPT/UnderstandAnyProjects_MIT
export LANGFLOW_SUPERUSER_PASSWORD="$(openssl rand -hex 16)"
./tools/run_langflow_mac.sh
```

Open <http://127.0.0.1:7860> and sign in with the username `felix` and the
password held in `LANGFLOW_SUPERUSER_PASSWORD`. The launcher imports both
`Jarvis studio flow` and `Jarvis voice flow` automatically. Re-running it is
safe: existing flows are not duplicated.

The Docker container receives the component pack and the `agent_runtime` and
`voice_common` source packages as read-only mounts. The imported copy of each
flow points at `http://host.docker.internal:8868`; that reaches the Mac side
of the SSH tunnel, which forwards to Jetson's loopback-only runtime. No
Jetson port is opened to the LAN or internet.

## What should be visible

The Studio canvas contains the actual ADR-0031 chain, including:

- `Jarvis Flow Turn`
- `Split compound request`
- `Identify speaker`
- `Ring policy gate`
- `Yield the indexer`
- `Assemble context`
- `Project knowledge pin`
- `Group chat pin`
- `Knowledge first (gbrain)`
- `Route intent & act`
- `Compose reply (persona)`
- `Record turn`

The imported Studio flow has 18 nodes and 17 edges. A canvas execution replays
the selected turn through Jetson's `/v1/agent/flow/turn` endpoint. It does not
grant access to project files and it cannot bypass HomeHub `AccessContext`.

## Native alternative

The HomeHub component README also documents a native Mac virtualenv install.
That mode uses `http://127.0.0.1:8868` directly after the same SSH tunnel, but
the pinned Docker launcher is the reproducible default because it avoids
changing the HomeHub runtime virtualenv on the Mac.

## Troubleshooting

- `Jetson agent-runtime is not reachable`: run
  `ssh jetson-us-cf 'curl -fsS http://127.0.0.1:8868/health'` and verify it
  returns `service: homehub-agent-runtime`.
- `Langflow did not become healthy`: run `docker logs uyp-langflow`.
- A flow is missing: remove the local container and rerun the launcher;
  imports are stored in the container's local database.
- Stop the UI with `docker rm -f uyp-langflow`. The SSH tunnel can be closed
  separately after checking its PID with `lsof -nP -iTCP:8868 -sTCP:LISTEN`.
