import { useEffect, useId, useState } from "react";

import { ApiError, OFFLINE, SESSION_EXPIRED, onApiEvent } from "@/api";
import { getMe, type Me } from "@/api/me";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { navigate, useNotAllowed, usePath } from "@/router";
import { LoadError } from "@/screens/LoadError";
import { ItemScreen } from "@/screens/ItemScreen";
import { Loading } from "@/screens/Loading";
import { NoAccess } from "@/screens/NoAccess";
import { Offline } from "@/screens/Offline";
import { QueueScreen } from "@/screens/QueueScreen";
import { SignedOut, signInHref } from "@/screens/SignedOut";
import { SurfacePage } from "@/screens/SurfacePage";
import { Nav } from "@/shell/Nav";
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

/** The invoice id of `/queue/:invoiceId`. */
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
  const sheetHeading = useId();
  const dialogHeading = useId();

  useEffect(() => {
    const stopExpired = onApiEvent(SESSION_EXPIRED, () => {
      // Dialogs stack one level deep at most: the Sheet gives way.
      setMenuOpen(false);
      setSessionExpired(true);
    });
    const stopOffline = onApiEvent(OFFLINE, () => {
      setMenuOpen(false);
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
    content = <Offline onRetry={retry} />;
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
          {/* One live region for the shell's notices, in the page from the start so its
              new text is announced (4.1.3): the one-shot "Not allowed" alert and the
              offline line. */}
          <div role="alert" data-testid="shell-notice">
            {offline ? (
              <p className="max-w-prose rounded-md border px-4 py-3">
                {strings.offline}
              </p>
            ) : notAllowed && route?.kind === "page" ? (
              <p className="rounded-md border border-destructive px-4 py-3">
                {strings.notAllowed}
              </p>
            ) : null}
          </div>
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
    </div>
  );
}
