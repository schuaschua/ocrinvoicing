import { Button } from "@/components/ui/button";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/** The built-in auth sign-in, returning to `returnTo` (a same-origin path). */
export function signInHref(returnTo: string): string {
  // Only a path on this origin: "//host" or "/\\host" would leave it.
  const safe = /^\/(?![/\\])/.test(returnTo) ? returnTo : "/";
  return `/.auth/login/aad?post_login_redirect_uri=${encodeURIComponent(safe)}`;
}

/** The sign-in check answered 401: the page behind the session-ended dialog. */
export function SignedOut({ returnTo }: { returnTo: string }) {
  const heading = usePageHeading(pageTitle(strings.sessionExpired));
  return (
    <div className="flex max-w-prose flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl">
        {strings.sessionExpired}
      </h1>
      <div>
        <Button asChild>
          <a href={signInHref(returnTo)}>{strings.signIn}</a>
        </Button>
      </div>
    </div>
  );
}
