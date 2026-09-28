// The staff app's surfaces and who may use them (EXPERIENCE.md Information
// Architecture, AD-14, UX-DR8). This is navigation only: staff-api checks every
// route's roles itself (backend/src/invoicing/domain/roles.py holds the same map, and
// a backend test keeps the two equal). Client routes never start with admin/ or
// runtime/, which the Functions host reserves (Story 1.4).

import { strings } from "@/strings";

/** The staff-api app roles, in landing order. */
export const ROLE_ORDER = [
  "admin",
  "finance",
  "procurement",
  "management",
  "goods_in",
] as const;
export type Role = (typeof ROLE_ORDER)[number];

export type SurfaceId = keyof typeof strings.surfaces;

export interface Surface {
  id: SurfaceId;
  /** The route. A trailing `/:param` matches one more path segment. */
  path: string;
  roles: readonly Role[];
  /** Listed in the sidebar; the others are reached from a row on another surface. */
  nav: boolean;
}

// In the order of EXPERIENCE.md's table, which is also the sidebar's order.
export const SURFACES: readonly Surface[] = [
  { id: "admin_queue", path: "/queue", roles: ["admin"], nav: true },
  { id: "admin_item", path: "/queue/:invoiceId", roles: ["admin"], nav: false },
  { id: "goods_in_scan", path: "/goods-in", roles: ["goods_in"], nav: true },
  { id: "invoices", path: "/invoices", roles: ["admin", "finance"], nav: true },
  {
    id: "overdue_pos",
    path: "/overdue-pos",
    roles: ["admin", "procurement", "finance"],
    nav: true,
  },
  {
    id: "suppliers",
    path: "/suppliers",
    roles: ["procurement", "finance", "management"],
    nav: true,
  },
  {
    id: "supplier_scorecard",
    path: "/suppliers/:supplierId",
    roles: ["procurement", "finance", "management"],
    nav: false,
  },
  {
    id: "price_comparison",
    path: "/price-comparison",
    roles: ["procurement", "finance"],
    nav: true,
  },
  {
    id: "watchlist",
    path: "/watchlist",
    roles: ["procurement", "management"],
    nav: true,
  },
  {
    id: "finance_month",
    path: "/finance-month",
    roles: ["finance", "management"],
    nav: true,
  },
];

/** Each role's landing page (EXPERIENCE.md "Reached from"). */
export const LANDING: Readonly<Record<Role, SurfaceId>> = {
  admin: "admin_queue",
  finance: "finance_month",
  procurement: "suppliers",
  management: "watchlist",
  goods_in: "goods_in_scan",
};

/** The app roles among `values`, once each, in landing order; anything else is dropped. */
export function knownRoles(values: readonly unknown[]): Role[] {
  return ROLE_ORDER.filter((role) => values.includes(role));
}

/** The union of `roles`' surfaces, in table order. */
export function surfacesFor(roles: readonly Role[]): Surface[] {
  return SURFACES.filter((surface) =>
    surface.roles.some((role) => roles.includes(role)),
  );
}

export function surfaceById(id: SurfaceId): Surface {
  const surface = SURFACES.find((candidate) => candidate.id === id);
  if (!surface) throw new Error(`unknown surface ${id}`);
  return surface;
}

/** The landing surface of the first held role in ROLE_ORDER; null with no role. */
export function landingFor(roles: readonly Role[]): Surface | null {
  const first = ROLE_ORDER.find((role) => roles.includes(role));
  return first === undefined ? null : surfaceById(LANDING[first]);
}

/** The surface whose route matches `path` (no query or fragment), or null. */
export function surfaceForPath(path: string): Surface | null {
  const parts = path.replace(/\/+$/, "").split("/");
  return (
    SURFACES.find((surface) => {
      const pattern = surface.path.split("/");
      return (
        pattern.length === parts.length &&
        pattern.every((segment, i) =>
          segment.startsWith(":")
            ? (parts[i] ?? "") !== ""
            : segment === parts[i],
        )
      );
    }) ?? null
  );
}

export function canOpen(roles: readonly Role[], surface: Surface): boolean {
  return surface.roles.some((role) => roles.includes(role));
}
