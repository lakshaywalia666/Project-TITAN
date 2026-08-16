# Identity evolution

The laptop bootstrap uses a high-entropy static administrator token whose SHA-256 is
compared in constant time. Automation and workload labs may additionally use
short-lived HS256 JWTs with strict algorithm, signature, issuer, audience, expiry,
not-before, subject, roles and project claims. Both methods can coexist during
migration.

The local JWT secret is a learning boundary, not an Internet-scale identity
provider. A production deployment should replace it with OIDC/JWKS verification or
SPIFFE workload identities backed by an external issuer and automated key rotation.
Unsigned or `alg=none` tokens are never decoded as identities. Roles in a prompt,
header or unsigned document have no effect.

