# Software supply-chain policy

- Python bootstrap services have no third-party runtime dependency.
- The portal is installed exclusively from `pnpm-lock.yaml`; native install scripts
  are explicitly allow-listed by package name.
- Pull requests compile and test services, render deployment manifests, build the
  image, scan secrets and high/critical vulnerabilities, and produce a CycloneDX
  SBOM.
- Version tags publish one immutable image with build provenance and keyless Sigstore
  signature. Deployment environments should resolve the tag to its digest.
- The optional Kyverno baseline rejects `latest` and requires restricted containers.

An alert is not waived only to make CI green. A waiver must identify the exact
advisory, affected component, reachability analysis, owner and expiry date.

