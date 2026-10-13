# Security policy

Report a suspected vulnerability privately to [support@anis.ly](mailto:support@anis.ly). Please include the affected package version, Python version, a description of the impact, and a safe way to reproduce the issue. Do not include live private keys, enrollment tokens, card codes, or customer data in a report.

The SDK team will acknowledge reports and coordinate a fix and disclosure with the reporter.

Version 2.x requires the `anis-response-v2` profile and rejects compromised, retired-after-stop, and premature next-key signatures. See [security and key custody](docs/security.md) for verification rules and [errors](docs/errors.md) for the closed refusal vocabulary. 1.x is deprecated — upgrade.
