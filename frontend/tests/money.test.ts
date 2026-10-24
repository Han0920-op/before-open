import { describe, expect, it } from "vitest";
import { centsInput, formatCents, parseCents, parseQuantity } from "../src/lib/money";

describe("integer money and quantity boundaries", () => {
  it.each([["0", 0], ["0.01", 1], ["9.9", 990], ["9.99", 999], ["10000000", 1000000000]] as const)("parses %s exactly", (value, expected) => {
    expect(parseCents(value)).toBe(expected);
    expect(parseCents(centsInput(expected))).toBe(expected);
  });
  it.each(["-1", "1.001", "1e3", "Infinity", "NaN", "10000000.01", " 1 ", "1."])("rejects invalid amount %s", (value) => expect(() => parseCents(value)).toThrow());
  it("keeps empty values unknown and zero explicit", () => {
    expect(parseCents("")).toBeNull(); expect(parseQuantity("")).toBeNull();
    expect(parseQuantity("0")).toBe(0); expect(formatCents(null)).toBe("待确认");
  });
  it.each(["1.5", "-1", "1000001", "1e2"])("rejects quantity %s", (value) => expect(() => parseQuantity(value)).toThrow());
  it("rejects zero job duration", () => expect(() => parseQuantity("0", 1)).toThrow());
  it("renders signed large cent amounts without floating rounding", () => {
    expect(formatCents(-11700)).toBe("−¥117.00");
    expect(formatCents(9007199254740991)).toBe("¥90,071,992,547,409.91");
  });
});
