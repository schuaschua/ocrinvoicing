import { useEffect, useId, useState } from "react";

import { ApiError, OFFLINE, SESSION_EXPIRED, onApiEvent } from "@/api";
import { getMe, type Me } from "@/api/me";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { navigate, useNotAllowed, usePath } from "@/router";
import { GoodsInScreen } from "@/screens/GoodsInScreen";
import { LoadError } from "@/screens/LoadError";
import { InvoiceDetailScreen } from "@/screens/InvoiceDetailScreen";
import { InvoicesScreen } from "@/screens/InvoicesScreen";
import { ItemScreen } from "@/screens/ItemScreen";
import { Loading } from "@/screens/Loading";
import { NoAccess } from "@/screens/NoAccess";
import { Offline } from "@/screens/Offline";
import { OverduePosScreen } from "@/screens/OverduePosScreen";
import { QueueScreen } from "@/screens/QueueScreen";
import { SignedOut, signInHref } from "@/screens/SignedOut";
import { SurfacePage } from "@/screens/SurfacePage";
import { Nav } from "@/shell/Nav";
import { leftFor, useNotice } from "@/shell/notices";
import { useShortcuts, useShortcutsEnabled } from "@/shell/shortcuts";
import { ShortcutsToggle } from "@/shell/ShortcutsToggle";
import { strings } from "@/strings";
import {
  canOpen,
  landingFor,
  surfaceForPath,
  surfacesFor,
  type Surface,
} from "@/surfaces";

type Session =
  | { kind: "loading" }
  | { kind: "ready"; me: Me }
  | { kind: "signed-out" }
  | { kind: "error"; message: string };

/** Where the user is, once signed in: the page to show, or a redirect to make. */
type Route =
  | { kind: "page"; surface: Surface }
  | { kind: "redirect"; to: Surface; notAllowed: boolean }
  | { kind: "no-access" };

function routeFor(me: Me, path: string): Route {
  const landing = landingFor(me.roles);
  if (landing === null) return { kind: "no-access" };
  const surface = surfaceForPath(path);
  if (surface === null) {
    // "/" and unknown paths go to the landing page, with no alert.
    return { kind: "redirect", to: landing, notAllowed: false };
  }
  if (!canOpen(me.roles, surface)) {
    return { kind: "redirect", to: landing, notAllowed: true };
  }
  return { kind: "page", surface };
}

/** The invoice id of `/queue/:invoiceId` or `/invoices/:invoiceId`. */
function itemIdFrom(path: string): string {
  const segment = path.split("/")[2] ?? "";
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** 1024px and wider: the sidebar, not the Sheet (EXPERIENCE.md Responsive). */
const WIDE_QUERY = "(min-width: 1024px)";
const SIGN_OUT_HREF = "/.auth/logout";

function currentLocation(): string {
  return `${window.location.pathname}${window.location.search}`;
}

/**
 * The staff app (AD-14, UX-DR8): the "Babaloo" text header (DESIGN.md: no logo), the
 * role-filtered sidebar (a Sheet below 1024px), one page per route, and the states the
 * API client raises: the session-ended dialog on 401 and the full-page offline notice on
 * 503 `DB_OFFLINE` (EXPERIENCE.md State Patterns).
 */
export function App() {
  const [session, setSession] = useState<Session>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [offline, setOffline] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const path = usePath();
  const notAllowed = useNotAllowed();
  const notice = useNotice(path);
  useEffect(() => leftFor(path), [path]);
  const sheetHeading = useId();
  const dialogHeading = useId();
  const helpHeading = useId();
  const shortcutsOn = useShortcutsEnabled();
  const [helpOpen, setHelpOpen] = useState(false);
  // Turned off (here or in another tab): the help closes and stays closed.
  if (!shortcutsOn && helpOpen) setHelpOpen(false);
  useShortcuts({
    "?": session.kind === "ready" ? () => setHelpOpen(true) : undefined,
  });

  useEffect(() => {
    const stopExpired = onApiEvent(SESSION_EXPIRED, () => {
      // Dialogs stack one level deep at most: the Sheet gives way.
      setMenuOpen(false);
      setHelpOpen(false);
      setSessionExpired(true);
    });
    const stopOffline = onApiEvent(OFFLINE, () => {
      setMenuOpen(false);
      setHelpOpen(false);
      setOffline(true);
    });
    return () => {
      stopExpired();
      stopOffline();
    };
  }, []);

  useEffect(() => {
    // The Sheet is for narrow windows only: widening past 1024px shows the sidebar, so
    // an open Sheet would keep trapping focus. Close it on that change.
    if (typeof window.matchMedia !== "function") return;
    const wide = window.matchMedia(WIDE_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) setMenuOpen(false);
    };
    wide.addEventListener("change", onChange);
    return () => wide.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    getMe(controller.signal).then(
      (me) => {
        if (!cancelled) setSession({ kind: "ready", me });
      },
      (error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) {
          setSession({ kind: "signed-out" });
        } else if (error instanceof ApiError && error.code === "DB_OFFLINE") {
          // The offline event has already switched to the offline notice.
          setSession({ kind: "loading" });
        } else {
          // A timeout reads like a network failure: nothing came back.
          const network =
            (error instanceof ApiError && error.status === 0) ||
            (error instanceof DOMException && error.name === "TimeoutError");
          setSession({
            kind: "error",
            message: network ? strings.errors.network : strings.errors.generic,
          });
        }
      },
    );
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [attempt]);

  const route = session.kind === "ready" ? routeFor(session.me, path) : null;
  // EXPERIENCE.md State Patterns: the goods-in scan has its own "Database stopped"
  // words (keep the paper with the delivery), every other page the system's.
  const goodsIn =
    route?.kind === "page" && route.surface.id === "goods_in_scan";
  const offlineText = goodsIn ? strings.goodsIn.unavailable : strings.offline;

  const redirectTo = route?.kind === "redirect" ? route.to.path : null;
  const redirectNotAllowed = route?.kind === "redirect" && route.notAllowed;
  useEffect(() => {
    // A route outside the user's roles, "/" or an unknown path: to the landing page,
    // replacing the entry so Back doesn't return to the refused route.
    if (redirectTo !== null) {
      navigate(redirectTo, { replace: true, notAllowed: redirectNotAllowed });
    }
  }, [redirectTo, redirectNotAllowed]);

  function retry() {
    setOffline(false);
    setSession({ kind: "loading" });
    setAttempt((n) => n + 1);
  }

  const navItems =
    session.kind === "ready" && !offline
      ? surfacesFor(session.me.roles).filter((surface) => surface.nav)
      : [];
  const active = route?.kind === "page" ? route.surface : null;

  let content;
  if (offline) {
    content = (
      <Offline
        heading={
          goodsIn ? strings.goodsIn.unavailableHeading : strings.offlineHeading
        }
        onRetry={retry}
      />
    );
  } else if (session.kind === "loading") {
    content = <Loading />;
  } else if (session.kind === "signed-out") {
    content = <SignedOut returnTo={currentLocation()} />;
  } else if (session.kind === "error") {
    content = <LoadError message={session.message} onRetry={retry} />;
  } else if (route?.kind === "no-access") {
    content = <NoAccess />;
  } else if (route?.kind === "page") {
    // A new page per path, so each route change moves focus to its h1.
    if (route.surface.id === "admin_queue") {
      content = <QueueScreen key={path} />;
    } else if (route.surface.id === "admin_item") {
      content = <ItemScreen key={path} invoiceId={itemIdFrom(path)} />;
    } else if (route.surface.id === "goods_in_scan") {
      content = <GoodsInScreen key={path} />;
    } else if (route.surface.id === "invoices") {
      content = <InvoicesScreen key={path} />;
    } else if (route.surface.id === "invoice_detail") {
      content = <InvoiceDetailScreen key={path} invoiceId={itemIdFrom(path)} />;
    } else if (route.surface.id === "overdue_pos") {
      content = <OverduePosScreen key={path} />;
    } else {
      content = <SurfacePage key={path} surface={route.surface} />;
    }
  } else {
    content = <Loading />;
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-10 flex h-header items-center gap-3 border-b bg-background px-4">
        {navItems.length > 0 ? (
          <Button
            type="button"
            variant="outline"
            className="lg:hidden"
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            {strings.nav.menu}
          </Button>
        ) : null}
        <p className="text-lg font-semibold">{strings.appName}</p>
        {session.kind === "ready" ? (
          <div className="ml-auto flex min-w-0 items-center gap-2">
            {session.me.name ? (
              <p className="hidden truncate text-sm sm:block">
                {session.me.name}
              </p>
            ) : null}
            {/* Story 2.11: off by default, kept in this browser only. Below 640px
                it sits in the Sheet instead, so the header fits 320px. */}
            <ShortcutsToggle className="hidden sm:inline-flex" />
            <Button asChild variant="ghost">
              <a href={SIGN_OUT_HREF}>{strings.signOut}</a>
            </Button>
          </div>
        ) : null}
      </header>
      <div className="flex flex-1">
        {navItems.length > 0 ? (
          // 1024px and wider: the sidebar; below that, the Sheet from the Menu button.
          <aside className="hidden w-64 shrink-0 border-r p-3 lg:block">
            <Nav items={navItems} active={active} />
          </aside>
        ) : null}
        <main id="main" className="flex min-w-0 flex-1 flex-col gap-4 p-4">
          {/* Live regions for the shell's notices, in the page from the start so their
              new text is announced (4.1.3): the one-shot "Not allowed" alert, the
              offline line and a screen's alert; and, once signed in, the Toast (Story
              2.10). Inline, so they never cover the focused element (2.4.11). */}
          <div role="alert" data-testid="shell-notice">
            {offline ? (
              <p className="max-w-prose rounded-md border px-4 py-3">
                {offlineText}
              </p>
            ) : notice?.kind === "alert" ? (
              <p className="max-w-prose rounded-md border border-destructive px-4 py-3">
                {notice.message}
              </p>
            ) : notAllowed && route?.kind === "page" ? (
              <p className="rounded-md border border-destructive px-4 py-3">
                {strings.notAllowed}
              </p>
            ) : null}
          </div>
          {session.kind === "ready" ? (
            <div role="status" data-testid="shell-toast">
              {notice?.kind === "status" && !offline ? (
                <p className="max-w-prose rounded-md border bg-card px-4 py-3 font-medium">
                  {notice.message}
                </p>
              ) : null}
            </div>
          ) : null}
          {content}
        </main>
      </div>

      <Modal
        open={menuOpen && navItems.length > 0}
        onClose={() => setMenuOpen(false)}
        labelledBy={sheetHeading}
        className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-72 max-w-[calc(100vw-3rem)] border-r p-4 lg:hidden"
      >
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 id={sheetHeading} className="text-lg font-semibold">
            {strings.appName}
          </h2>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setMenuOpen(false)}
          >
            {strings.nav.close}
          </Button>
        </div>
        <Nav
          items={navItems}
          active={active}
          onNavigate={() => setMenuOpen(false)}
        />
        <ShortcutsToggle className="mt-3 sm:hidden" />
      </Modal>

      <Modal
        open={sessionExpired}
        onClose={() => {
          // Closed without signing in: the page behind keeps the sign-in link.
          setSessionExpired(false);
          setSession({ kind: "signed-out" });
        }}
        labelledBy={dialogHeading}
        className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg border p-6"
      >
        <h2 id={dialogHeading} className="mb-4 text-lg font-semibold">
          {strings.sessionExpired}
        </h2>
        <Button asChild>
          <a href={signInHref(currentLocation())}>{strings.signIn}</a>
        </Button>
      </Modal>

      <Modal
        open={helpOpen && shortcutsOn && !sessionExpired}
        onClose={() => setHelpOpen(false)}
        labelledBy={helpHeading}
        className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border p-6"
      >
        <h2 id={helpHeading} className="mb-2 text-lg font-semibold">
          {strings.shortcuts.helpHeading}
        </h2>
        <p className="mb-4">{strings.shortcuts.helpIntro}</p>
        <table className="mb-4 w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th scope="col" className="py-1 pr-4">
                {strings.shortcuts.keyColumn}
              </th>
              <th scope="col" className="py-1">
                {strings.shortcuts.actionColumn}
              </th>
            </tr>
          </thead>
          <tbody>
            {strings.shortcuts.keys.map((row) => (
              <tr key={row.key} className="border-b">
                <td className="py-1 pr-4">
                  <kbd className="rounded border px-1 font-mono">{row.key}</kbd>
                </td>
                <td className="py-1">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Button type="button" onClick={() => setHelpOpen(false)}>
          {strings.shortcuts.close}
        </Button>
      </Modal>
    </div>
  );
}
