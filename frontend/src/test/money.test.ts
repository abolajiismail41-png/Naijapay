import { describe, expect, it } from "vitest";
import { formatKobo, formatKoboShort, parseNairaToKobo, parseScaled } from "../lib/money";

describe("money", () => {
  it("formats integer kobo exactly", () => {
    expect(formatKobo(505_000)).toBe("₦5,050.00");
    expect(formatKobo(5)).toBe("₦0.05");
    expect(formatKobo(-12_345)).toBe("-₦123.45");
    expect(formatKoboShort(500_000)).toBe("₦5,000");
    expect(formatKoboShort(500_050)).toBe("₦5,000.50");
  });
  it("parses typed amounts without floating point", () => {
    expect(parseNairaToKobo("5,000")).toBe(500_000);
    expect(parseNairaToKobo("₦ 5000.5")).toBe(500_050);
    expect(parseNairaToKobo("0.07")).toBe(7);
    expect(parseNairaToKobo("19.99")).toBe(1_999);
  });
  it("rejects anything that is not a plain amount", () => {
    for (const bad of ["", "abc", "-5", "5.555", "1e3", "5..0", "₦", "1,00,0.0.0"]) expect(parseNairaToKobo(bad)).toBeNull();
    expect(parseNairaToKobo("99999999999999999999")).toBeNull();
  });
  it("converts percentages to basis points", () => {
    expect(parseScaled("2", 2)).toBe(200);
    expect(parseScaled("2.5", 2)).toBe(250);
    expect(parseScaled("0.01", 2)).toBe(1);
    expect(parseScaled("2.555", 2)).toBeNull();
  });
});
