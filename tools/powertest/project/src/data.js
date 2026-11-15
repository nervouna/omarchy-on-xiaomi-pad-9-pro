// A fixed, generated inventory: the same 240 rows on every load.
const NAMES = ["bolt", "nut", "washer", "spring", "bearing", "gear", "shaft", "bracket"];
const SIZES = ["M2", "M3", "M4", "M5", "M6"];

export function parts() {
  const rows = [];
  let seed = 7;
  for (let i = 0; i < 240; i++) {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    rows.push({
      name: `${NAMES[i % NAMES.length]} ${SIZES[i % SIZES.length]}`,
      bin: `B${String(1 + (seed % 60)).padStart(2, "0")}`,
      count: seed % 500,
      price: (seed % 2000) / 100,
    });
  }
  return rows;
}
