import { describe, expect, it } from "vitest";
import { formatCents, formatSignedCents } from "@/lib/money";

describe("formatCents", () => {
  it("renders whole dollars without decimals", () => {
    expect(formatCents(50000)).toBe("$500");
  });
  it("renders sub-dollar amounts with two decimals", () => {
    expect(formatCents(1250)).toBe("$12.50");
  });
  it("renders zero", () => {
    expect(formatCents(0)).toBe("$0");
  });
});

describe("formatSignedCents", () => {
  it("prefixes gains with +", () => {
    expect(formatSignedCents(50000)).toBe("+$500");
  });
  it("prefixes losses with a minus sign", () => {
    expect(formatSignedCents(-1250)).toBe("−$12.50");
  });
  it("leaves zero unsigned", () => {
    expect(formatSignedCents(0)).toBe("$0");
  });
});
