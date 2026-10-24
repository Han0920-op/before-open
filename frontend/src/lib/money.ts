/** Decimal input is converted with integer arithmetic, never rounded from a JS float. */
export function parseCents(text: string): number | null {
  if (!text.trim()) return null;
  if (text.length > 20 || !/^\d+(?:\.\d{1,2})?$/.test(text)) throw new Error("请输入不超过两位小数的非负金额");
  const [yuan = "0", fraction = ""] = text.split(".");
  const cents = BigInt(yuan) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents > 1_000_000_000n) throw new Error("金额超出当前可预演范围");
  return Number(cents);
}

export function parseQuantity(text: string, min = 0): number | null {
  if (!text.trim()) return null;
  if (!/^\d+$/.test(text)) throw new Error("请输入非负整数");
  const value = Number(text);
  if (!Number.isSafeInteger(value) || value < min || value > 1_000_000) {
    throw new Error(min === 1 ? "请输入 1～1,000,000 之间的整数" : "数量超出当前可预演范围");
  }
  return value;
}

export function centsInput(value: number | null): string {
  if (value === null) return "";
  const cents = BigInt(value);
  return `${cents / 100n}.${(cents % 100n).toString().padStart(2, "0")}`;
}

export function formatCents(value: number | null | undefined): string {
  if (value == null) return "待确认";
  const cents = BigInt(value), absolute = cents < 0n ? -cents : cents;
  return `${cents < 0n ? "−" : ""}¥${(absolute / 100n).toLocaleString("zh-CN")}.${(absolute % 100n).toString().padStart(2, "0")}`;
}
