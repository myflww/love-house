# Official Harness CLI connection QA

This private fixture pins official `@deepseek-ai/dsh` 0.2.1-rc.5 and all dependency integrity hashes. Run `npm ci --ignore-scripts --no-audit --no-fund` in this directory. No Node dependencies are shipped in Love House installers.

Official top-level tarball: https://registry.npmjs.org/@deepseek-ai/dsh/-/dsh-0.2.1-rc.5.tgz

Reviewed integrity:

```text
sha512-WkyJZv4zl9sCAxSzRctGm58m0rilGqwR6pniBiLOz5CPDfHfDuAUicg0AAazXI7oj/Cph6/cjNTncA/rpLTXpw==
```

From the repository root run `scripts/verify_harness_connection.py --node <node-executable> --cli examples/harness-cli-qa/node_modules/@deepseek-ai/dsh/lib/bin.js --report-dir <local-report-directory>`. It uses isolated profiles and a local synthetic model. It must save actual host turns in both connection modes, exclude a second actual session, and exit nonzero on failure.
