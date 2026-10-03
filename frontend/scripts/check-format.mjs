import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const project = dirname(dirname(fileURLToPath(import.meta.url)));
const output = mkdtempSync(join(tmpdir(), "wallet-atlas-format-"));
try {
  execFileSync(
    process.execPath,
    [
      join(project, "node_modules/typescript/bin/tsc"),
      "src/format.ts",
      "--target",
      "ES2022",
      "--module",
      "commonjs",
      "--skipLibCheck",
      "--outDir",
      output,
    ],
    { cwd: project, stdio: "inherit" },
  );
  const { decimal, compareDecimal, parseAddresses } = createRequire(
    import.meta.url,
  )(join(output, "format.js"));
  const samples = [
    ["8.7493", 2, "8.75"],
    ["12.499", 2, "12.5"],
    ["-0.0000050", 2, "0"],
    ["-0.005", 2, "-0.01"],
    ["999999999999999999999999.995", 2, "1,000,000,000,000,000,000,000,000"],
    ["999.995", 2, "1,000"],
    ["0.000005", 9, "0.000005"],
    ["0.000000001", 9, "0.000000001"],
    ["12.5", 0, "13"],
    ["-12.5", 0, "-13"],
    [null, 2, "—"],
  ];
  for (const [value, places, expected] of samples)
    assert.equal(
      decimal(value, places),
      expected,
      `format ${value} at ${places} places`,
    );
  assert.equal(
    compareDecimal("9007199254740993.01", "9007199254740993.001"),
    1,
  );
  assert.equal(compareDecimal("-0.000000001", "0"), -1);
  assert.equal(compareDecimal("12.50", "12.5"), 0);
  const address = "11111111111111111111111111111111";
  assert.deepEqual(parseAddresses(`address,label\n${address},System`), {
    addresses: [address],
    invalid: [],
  });
  assert.deepEqual(parseAddresses(JSON.stringify([address, address])), {
    addresses: [address],
    invalid: [],
  });
  console.log("16 exact formatting, ordering, and import assertions passed.");
} finally {
  rmSync(output, { recursive: true, force: true });
}
