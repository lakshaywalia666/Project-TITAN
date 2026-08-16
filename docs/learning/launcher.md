# Project TITAN launcher

`titan.cmd` is the Windows entry point for starting and checking Project TITAN.
It calls the auditable `titan.ps1` PowerShell launcher and changes no machine-wide
PowerShell policy.

## First local start

1. Double-click `titan.cmd` or run `powershell -File .\titan.ps1 menu` from the
   repository root.
2. Choose **Check this computer**. Install or start anything marked as required.
   A local start requires Docker Desktop; the portal also needs Node.js 22 and
   pnpm 11.
3. Choose **Start local TITAN**. The launcher creates an ignored `.env` with a
   cryptographically random administrator token, builds the containers, starts
   them on loopback and performs health and authentication checks.
4. Choose **Start local TITAN with portal** to also start the interface at
   `http://127.0.0.1:3000`.
5. Use **Show local status** or **Stop local TITAN** when finished. Stop preserves
   Docker data volumes.

Equivalent non-interactive commands are:

```powershell
.\titan.ps1 doctor
.\titan.ps1 local-up
.\titan.ps1 local-up -Portal -Observability
.\titan.ps1 local-status
.\titan.ps1 local-down
```

## Inject GitHub and cloud identifiers

Run:

```powershell
.\titan.ps1 init
```

Edit the generated `.titan/settings.json`. It is ignored by Git. Copy only public
identifiers into it: repository name, regions, role ARN, Azure IDs, GCP Workload
Identity provider and service-account email, and the public signed GHCR digest.

The launcher intentionally rejects fields named like passwords, secrets, tokens,
private keys or access keys. It does not store cloud credentials. Provider-side
GitHub OIDC trust must be created once by an authenticated cloud administrator;
that trust cannot be bootstrapped safely by GitHub before the cloud knows which
repository to trust.

After the repository is pushed, the signed release exists, the GHCR package is
public and provider-side OIDC trust is ready, configure one provider's GitHub
environment variables:

```powershell
.\titan.ps1 github-configure `
  -Provider gcp `
  -ConfirmGitHub CONFIGURE_GITHUB_TITAN
```

Then trigger one disposable deployment:

```powershell
.\titan.ps1 cloud-smoke `
  -Provider gcp `
  -ConfirmCloud DEPLOY_AND_DESTROY_TITAN
```

Use `aws` or `azure` when that provider's OIDC fields are ready. The cloud action
still requires the existing GitHub environment gate, verifies the image signature,
restricts SSH, performs authenticated checks and attempts automatic destruction.
It cannot guarantee a zero bill, so always confirm deletion in the provider console.

## What the launcher will never do silently

- install software or modify global execution policy;
- accept or save long-lived cloud access keys;
- expose local application ports beyond loopback;
- overwrite an existing `.env` or settings file;
- create cloud resources without the exact deployment confirmation;
- delete local Docker data volumes during a normal stop.
