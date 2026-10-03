# Four-file review and next Codex task

Read `REVIEW.md` for findings and evidence limits. Give Codex `CODEX_NEXT_PRODUCT_MILESTONE.md` in the existing scanner repository. This supplements the existing work; do not overwrite user changes or create a competing issue register.

`proposed_fix/validate_receipt_guard.patch` is a small proposed change against **tools/validate.py**, whose supplied SHA-256 was `de0c1f12894dc3565699852f96a2613b7f1bbb6e1cc74b5374c582b1b876c30b`. `proposed_fix/validate.py` is the corresponding reference file, not an instruction to blindly replace a newer runner. Apply or reconcile only after inspecting the current source.

From the actual repository, use `git apply --check /path/to/proposed_fix/validate_receipt_guard.patch` before applying. Integrate the tests into the existing runner-test module. The isolated tests can also run as follows:

```sh
VALIDATOR_UNDER_REVIEW="$PWD/tools/validate.py" \
  python -m pytest -q /path/to/tests/test_validation_receipt_boundary.py
```

These tests stub all subprocesses and source/lock snapshots. They test runner decisions, not the real browser/application. The unchanged uploaded validator produced **25 passes and 7 ordinary failures**; the proposed correction produced **32 passes**. See `evidence/validator-tests.log`, `evidence/proposed-fix-tests.log` and the scenario JSON files. The full candidate backend, instruction matrix, installation and browser were not rerun here because the current source/fixtures/harness were not supplied.

The `evidence/input-integrity.json` manifest records actual uploaded-file hash matches and internal report consistency. It does not assert possession or verification of every listed candidate file. Original uploads and prior ZIPs remain unchanged.

The next engineering delivery should include the current complete source/evidence checkpoint and executable product progress. This package was not submitted to Codex automatically and is not an application release.
