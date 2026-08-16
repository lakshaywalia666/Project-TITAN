# Titan Command Center

The portal is the human-facing control surface for projects, desired resources,
operations, AI budgets, audit activity and security posture. It is built with React
19, vinext and Vite.

```bash
pnpm install --frozen-lockfile
pnpm run dev
pnpm run lint
pnpm run test
```

Local development runs without Cloudflare edge emulation so it works on Windows and
WSL. Set `TITAN_PORTAL_EDGE=1` only when testing the optional Worker adapter on a host
where `workerd` is supported.

The live connection dialog defaults to control port 8090 and AI port 8100. It keeps
the bearer token only in React memory; page reload disconnects the session. The APIs
allow CORS only from configured local origins by default.

The portal remains operationally optional. A portal failure does not stop APIs,
controllers or workloads, and every operation is also available through HTTP and CLI.

