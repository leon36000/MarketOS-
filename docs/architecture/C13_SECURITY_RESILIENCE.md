# C13 — Security, Audit and Resilience

Secrets are opaque references injected at runtime under least privilege. Raw values never return to the browser or model context and are redacted from logs and traces.

Code, images, dependencies, configuration and policies use exact versions, hashes, SBOMs and provenance. Unverified artifacts cannot enter sensitive services. Administrative changes require strong identity, reason, signed diff and append-only audit.

Incident response follows NIST SP 800-61 Rev. 3 aligned with CSF 2.0: prepare, detect, respond, recover and continuously improve. Runbooks cover credential exposure, unauthorized configuration, data poisoning, reconciliation failure, broker outage, storage corruption and compute compromise.

Recovery requires clean-environment restore, semantic reconciliation and requalification. Service recovery alone does not resume financial authority. Independent review and chaos/failure drills remain mandatory.
