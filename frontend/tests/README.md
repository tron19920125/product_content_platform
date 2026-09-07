# Studio browser regression

`studio-ui.mjs` drives the built Studio through Chromium and verifies actual API state and downloaded files. Run against a disposable data root; it creates and deletes its own fixtures. It never calls a real image model or planning provider.

The script needs Node, Playwright, and Chromium. Use a project-resolvable `playwright` package or point `PLAYWRIGHT_MODULE` at an existing `index.mjs`. `CHROME_PATH` selects an installed Chrome executable. The default URL is `http://127.0.0.1:8021`; `STUDIO_TEST_URL` overrides it.

See [the verification record](../../docs/UI交互检查与修复_2026-09-07.md) for setup and coverage. The suite exits nonzero on assertion failure, writes `results.json`, captures failed cases, and exports representative viewport screenshots. `STUDIO_TEST_FILTER` narrows the run by name regex, and `STUDIO_TEST_OUTPUT` controls the artifact directory.
