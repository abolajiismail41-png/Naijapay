import { describe, expect, it } from "vitest";
import { normalizePhone, toLocalPhone } from "../lib/phone";

describe("phone", () => {
  it("normalises Nigerian mobile formats", () => {
    for (const raw of ["08031234567", "+2348031234567", "2348031234567", "0803 123 4567", "0803-123-4567"]) expect(normalizePhone(raw)).toBe("+2348031234567");
    expect(toLocalPhone("+2348031234567")).toBe("08031234567");
  });
  it("rejects numbers the backend would reject", () => {
    for (const bad of ["", "12345", "0603123456", "+15551234567", "080312345678", "0803123456"]) expect(normalizePhone(bad)).toBeNull();
  });
});
