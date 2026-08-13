# C1 — Secrets, Identity and Private Access

## Principles

- Secrets are never committed, logged, embedded in images or returned to the browser.
- Applications consume opaque secret references and receive values only at runtime.
- The public repository contains examples and schemas only.
- Machine identity, human identity and data-encryption keys are separate concerns.

## Secret tiers

### S0 — bootstrap

SOPS with age is the preferred candidate for encrypted bootstrap material stored outside the public repository. Recovery keys require an offline copy and a documented rotation procedure.

### S1 — standalone runtime

systemd credentials are the preferred candidate for per-service injection on the standalone profile. Credentials are mounted into the service runtime rather than exported globally.

### S2 — distributed runtime

OpenBao is optional when multi-node secret versioning, machine authentication, PKI or Transit encryption creates measured value. Operating it introduces independent unseal, backup, upgrade and availability obligations.

## Human access

- Local or private-overlay access is the default.
- Tailscale is the preferred private-overlay candidate; device approval and tagged machine identities are required before admission.
- No MARKET-OS service is exposed publicly by default.
- Caddy is a candidate private reverse proxy bound only to approved interfaces.
- The final application identity provider is deferred to C14.

## Bootstrap over SSH

A temporary SSH credential may install the Node Pack, enroll a machine certificate and create the service identity. The bootstrap credential is then revoked or removed.

## Browser policy

The cockpit may accept a secret write once over TLS, but receives only a secret reference, health and rotation metadata. Secret readback, clipboard propagation and model-visible rendering are forbidden.

## Rotation

Every secret class defines owner, scope, creation time, rotation interval, last use, revocation procedure and dependent services. Rotation failure makes dependent sensitive services `NOT_READY`.
