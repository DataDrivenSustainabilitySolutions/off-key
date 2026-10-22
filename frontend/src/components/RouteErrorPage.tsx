import { isRouteErrorResponse, Link, useRouteError } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { BrandHome } from "@/components/BrandHome";
import { useDocumentTitle } from "@/hooks/use-document-title";

export function RouteErrorPage({ notFound = false }: { notFound?: boolean }) {
  useDocumentTitle(notFound ? "Page not found" : "Something went wrong");
  return (
    <main
      aria-labelledby="route-error-title"
      className="flex min-h-dvh items-center justify-center bg-background px-6 py-12 text-foreground"
    >
      <div className="w-full max-w-md space-y-6">
        <BrandHome />
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {notFound ? "404" : "Page unavailable"}
          </p>
          <h1 id="route-error-title" className="text-3xl font-semibold tracking-tight">
            {notFound ? "Page not found" : "Something went wrong"}
          </h1>
          <p className="leading-6 text-muted-foreground">
            {notFound
              ? "The page you're looking for doesn't exist or may have moved."
              : "We couldn't display this page. Reload it to try again, or return home."}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {!notFound && (
            <Button type="button" onClick={() => window.location.reload()}>
              Reload page
            </Button>
          )}
          <Button asChild variant={notFound ? "default" : "outline"}>
            <Link to="/" replace>Go home</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}

export function RouteErrorBoundary() {
  const error = useRouteError();
  return <RouteErrorPage notFound={isRouteErrorResponse(error) && error.status === 404} />;
}
