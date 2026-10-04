export const shorten = (address: string, head = 6) =>
  address.length > head * 2 + 3
    ? `${address.slice(0, head)}…${address.slice(-head)}`
    : address;
export const date = (value?: string) =>
  value
    ? new Date(value).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      })
    : "Not set";
export const dateTime = (value?: string) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: "UTC",
      })
    : "Not set";
export const count = (value: number | undefined) =>
  (value ?? 0).toLocaleString();
export const label = (value: string) =>
  value.replace(/_/g, " ").replace(/\b\w/g, (x) => x.toUpperCase());
export function decimal(value: string | null | undefined, places = 2): string {
  if (
    value === null ||
    value === undefined ||
    !/^[+-]?\d+(?:\.\d+)?$/.test(value)
  )
    return value ?? "—";
  const negative = value.startsWith("-");
  const raw = value.replace(/^[+-]/, "");
  const [whole, fraction = ""] = raw.split(".");
  const precision = Math.max(0, Math.min(100, Math.trunc(places)));
  const scale = 10n ** BigInt(precision);
  let rounded = BigInt(
    whole + fraction.slice(0, precision).padEnd(precision, "0"),
  );
  // Round the absolute exact decimal half up, without floating-point conversion.
  if ((fraction[precision] ?? "0") >= "5") rounded += 1n;
  const integer = (rounded / scale).toString();
  const significant = precision
    ? (rounded % scale).toString().padStart(precision, "0").replace(/0+$/, "")
    : "";
  return `${negative && rounded !== 0n ? "-" : ""}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${significant ? `.${significant}` : ""}`;
}
// Values stay decimal strings. This comparator never uses binary floating point.
export function compareDecimal(a?: string | null, b?: string | null): number {
  if (a === null || a === undefined)
    return b === null || b === undefined ? 0 : 1;
  if (b === null || b === undefined) return -1;
  if (!/^-?\d+(?:\.\d+)?$/.test(a) || !/^-?\d+(?:\.\d+)?$/.test(b))
    return a.localeCompare(b);
  const parts = (s: string) => {
    const [integer, fractional = ""] = s.replace(/^-/, "").split(".");
    return { negative: s.startsWith("-"), integer, fractional };
  };
  const x = parts(a),
    y = parts(b),
    places = Math.max(x.fractional.length, y.fractional.length);
  const left =
    BigInt(x.integer + x.fractional.padEnd(places, "0")) *
    (x.negative ? -1n : 1n);
  const right =
    BigInt(y.integer + y.fractional.padEnd(places, "0")) *
    (y.negative ? -1n : 1n);
  return left < right ? -1 : left > right ? 1 : 0;
}
const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function validAddress(address: string): boolean {
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address)) return false;
  let value = 0n;
  for (const char of address)
    value = value * 58n + BigInt(alphabet.indexOf(char));
  let bytes = 0;
  while (value > 0n) {
    bytes++;
    value >>= 8n;
  }
  return bytes + (address.match(/^1*/)?.[0].length ?? 0) === 32;
}
export function parseAddresses(input: string): {
  addresses: string[];
  invalid: string[];
} {
  let tokens: string[] = [];
  if (/^[\[{]/.test(input.trim())) {
    try {
      const data = JSON.parse(input);
      const entries = Array.isArray(data)
        ? data
        : (data.addresses ?? data.wallets ?? []);
      if (!Array.isArray(entries))
        return {
          addresses: [],
          invalid: ["JSON must contain an array of addresses."],
        };
      tokens = entries
        .map((item) =>
          typeof item === "string"
            ? item
            : (item?.address ?? item?.wallet ?? ""),
        )
        .filter(Boolean);
    } catch {
      return {
        addresses: [],
        invalid: [
          "Invalid JSON. Use an address array or an object with an addresses array.",
        ],
      };
    }
  } else {
    const rows = input.split(/\r?\n/).filter((x) => x.trim());
    const csvRows = rows.map((row) =>
      (row.match(/(?:"(?:[^"]|"")*"|[^,;]+)(?:[,;]|$)/g) ?? [row]).map((cell) =>
        cell
          .replace(/[,;]$/, "")
          .trim()
          .replace(/^"|"$/g, "")
          .replace(/""/g, '"'),
      ),
    );
    const headerIndex = csvRows[0]?.findIndex((cell) =>
      /^(address|wallet|wallet_address)$/i.test(cell),
    );
    if (headerIndex !== undefined && headerIndex >= 0)
      tokens = csvRows
        .slice(1)
        .map((row) => row[headerIndex] ?? "")
        .filter(Boolean);
    else
      tokens = rows
        .flatMap((row) => row.split(/[\s,;]+/))
        .map((x) => x.replace(/^"|"$/g, ""))
        .filter(Boolean);
  }
  tokens = tokens.map((token) => String(token).trim()).filter(Boolean);
  const addresses = [...new Set(tokens.filter(validAddress))];
  const invalid = [...new Set(tokens.filter((token) => !validAddress(token)))];
  return { addresses, invalid };
}
