# Native FM27 tactic release check

Run `npm run test:native-tactics` to check freshly generated native tactics against the audited installed FM27 ARM64 body reader. The check uses the current templates in your FM27 Tactics folder. It checks each original and generates three variants per supported template, covers every stored tackling selection, and cycles all seven mentalities. Files and receipts stay under this checkout's `tmp/`; original templates and Agent Outputs stay untouched.

The check pins the audited validator source and verifies the exact installed `game_plugin` SHA256. A missing or changed binary returns `unsupported_build` with exit code 2. Re-audit the native loader and its fingerprint before supporting another build. `PI_FM_NATIVE_BINARY` selects another installation path while retaining the same fingerprint requirement.

The optional check uses `uv` and Unicorn 2.1.4 with its cache under the external checkout. Complete `native_authoring` generation runs the bounded native emulator through the installed reader Python environment; the legacy scalar-only branches retain their previous codec route. The main regression gate also executes native authoring and finite native proof controls. The existing FM26 codec supplies archive generation and plaintext extraction; set `PI_FM_TACTIC_CODEC_ROOT` and `PI_FM_TACTIC_PYTHON` to use another verified codec installation.

Each positive case must reach the actual native body reader's successful return at exact EOF and reproduce its requested name, mentality and tackling flags. Each case also checks rejected bad magic, low schema, old envelope and truncated body controls. The harness supplies bounded stream, allocation and copy services; it executes the native parsing code. It verifies the decrypted tactic body, with archive encryption/decryption checked separately by the production writer's roundtrip. Full UI import and match-engine behavior remain separate evidence.

Agents should reserve a host slot for the complete check:

```bash
agent-host run --owner codex:pi-fm:native-release --purpose 'native FM27 tactic release check' -- npm run test:native-tactics
```

The normal Node gate also retains the original seven role-case tests and covers all26 directed role changes across nine exact prefixes. `stored-role-instructions.test.mjs` checks both pinned IP9 instruction profiles, original ARM clear/set routines, semantic/native drift refusals, and three generated archives through the immutable full body reader with all22 positions, roles and primary instruction vectors compared. These are offline proofs; personal overrides, role-derived selections, effective instructions, full UI setter parity and game import remain unverified.
