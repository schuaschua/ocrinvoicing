import { describe, expect, it } from "vitest";

import { strings } from "@/strings";
import {
  LANDING,
  ROLE_ORDER,
  SURFACES,
  canOpen,
  knownRoles,
  landingFor,
  surfaceById,
  surfaceForPath,
  surfacesFor,
} from "@/surfaces";

const ids = (list: { id: string }[]) => list.map((surface) => surface.id);

describe("2.7 surfaces by role (EXPERIENCE.md staff surface table, UX-DR8)", () => {
  it("knows the five app roles in landing order and drops anything else", () => {
    expect(ROLE_ORDER).toEqual([
      "admin",
      "finance",
      "procurement",
      "management",
      "goods_in",
    ]);
    expect(knownRoles(["goods_in", "Admin", "admin", 3, "admin"])).toEqual([
      "admin",
      "goods_in",
    ]);
  });

  it("gives each role only its own surfaces", () => {
    expect(ids(surfacesFor(["admin"]))).toEqual([
      "admin_queue",
      "admin_item",
      "invoices",
      "overdue_pos",
    ]);
    expect(ids(surfacesFor(["goods_in"]))).toEqual(["goods_in_scan"]);
    expect(ids(surfacesFor(["management"]))).toEqual([
      "suppliers",
      "supplier_scorecard",
      "watchlist",
      "finance_month",
    ]);
    expect(surfacesFor([])).toEqual([]);
  });

  it("lands on the first role's landing page in role order", () => {
    expect(landingFor(["goods_in", "admin"])?.path).toBe("/queue");
    expect(landingFor(["management", "procurement"])?.path).toBe("/suppliers");
    expect(landingFor(["management", "finance"])?.path).toBe("/finance-month");
    expect(landingFor([])).toBeNull();
    for (const [role, id] of Object.entries(LANDING)) {
      expect(surfaceById(id).roles).toContain(role);
    }
  });

  it("matches routes, with one segment for a parameter", () => {
    expect(surfaceForPath("/queue")?.id).toBe("admin_queue");
    expect(surfaceForPath("/queue/")?.id).toBe("admin_queue");
    expect(surfaceForPath("/queue/0199a1b2")?.id).toBe("admin_item");
    expect(surfaceForPath("/queue/0199a1b2/more")).toBeNull();
    expect(surfaceForPath("/suppliers/s-1")?.id).toBe("supplier_scorecard");
    expect(surfaceForPath("/")).toBeNull();
    expect(surfaceForPath("/nope")).toBeNull();
    expect(() => surfaceById("nope" as "watchlist")).toThrow();
  });

  it("never routes under admin/ or runtime/, which the Functions host reserves", () => {
    for (const surface of SURFACES) {
      expect(surface.path).not.toMatch(/^\/(admin|runtime)(\/|$)/);
      expect(strings.surfaces[surface.id]).toBeTruthy();
    }
    expect(new Set(SURFACES.map((s) => s.path)).size).toBe(SURFACES.length);
  });

  it("opens a surface only for one of its roles", () => {
    const queue = surfaceById("admin_queue");
    expect(canOpen(["admin", "goods_in"], queue)).toBe(true);
    expect(canOpen(["finance"], queue)).toBe(false);
  });
});
