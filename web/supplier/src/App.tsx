import { strings } from "@/strings";

/**
 * The supplier page shell: the "Babaloo" text header (DESIGN.md: no logo) and a
 * single column with the supplier gutter. Screens arrive with their stories.
 */
export function App() {
  return (
    <div className="min-h-dvh text-body-supplier">
      <header className="sticky top-0 z-10 flex h-header items-center border-b bg-background px-supplier-gutter">
        <p className="text-lg font-semibold">{strings.appName}</p>
      </header>
      <main id="main" className="px-supplier-gutter py-4" />
    </div>
  );
}
