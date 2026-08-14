# C14 — Configuration, Catalogs and Secrets

Providers, models, nodes, cloud profiles, sources, tools, broker accounts, risk policies and alerts are versioned resources with stable IDs, health, dependencies and status.

`+` creates a draft and validates connectivity/capability before activation. Disable precedes delete. `-` displays dependent agents, workflows, fallbacks, experiments and evidence before removal. Catalog refresh stores the raw response hash and normalized diff; models are never hard-coded as `latest`.

A secret can be written once over TLS to the server-side secret service. The cockpit receives only `secret_ref`, configured state, health and rotation metadata. Readback, copy-to-model, logs and browser persistence are forbidden.

Sensitive actions require strong reauthentication, typed justification, diff preview, permission check, explicit confirmation, server-side execution, postcondition and append-only receipt. Emergency safe-stop remains available even when the main UI is degraded.
