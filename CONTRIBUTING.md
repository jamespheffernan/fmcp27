# Contributing

Use [GitHub issues](https://github.com/jamespheffernan/fmcp27/issues) for bugs and proposals. Include the game build, macOS version, assistant, reproduction steps and the result you expected. Keep saves, credentials, personal data and game binaries out of issues and pull requests.

For a change, create a branch, keep the patch focused and run the checks for the affected code. Explain what the change makes possible and what you verified. See [the testing guide](docs/TESTING.md) for the suite's markers and game-build requirements.

Reader changes must keep missing data distinct from zero, check record identity and build compatibility, and preserve the boundary between reading the game and editing it. A stored counter or captured event does not establish a tactical cause. Include the source and limits of any new interpretation.

Website checks need Node.js and no installed game:

```sh
node --test site/tests/*.test.cjs
```

Private development captures and installed game resources are not part of the public checkout. Checks that require them are not a portable acceptance gate. Name any checks you could not run and why.
