import React, { Component, ReactNode } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { clientLogger } from "@/lib/logger";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.setState({
      error,
      errorInfo,
    });

    clientLogger.error({
      event: "ui.error_boundary_caught",
      message: "ErrorBoundary caught an error",
      error,
      context: { componentStack: errorInfo.componentStack },
    });

    // Call custom error handler if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  handleRetry = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default error UI
      return (
        <Card className="w-full max-w-md mx-auto mt-8 border-destructive">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-2">
              <AlertCircle className="h-12 w-12 text-destructive" />
            </div>
            <CardTitle className="text-destructive">Something went wrong</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p className="text-muted-foreground">
              An unexpected error occurred. Please try refreshing the page or contact support if the problem persists.
            </p>

            {this.state.error && (
              <details className="text-left">
                <summary className="cursor-pointer text-sm font-medium mb-2">
                  Error Details (for developers)
                </summary>
                <pre className="text-xs bg-muted p-2 rounded overflow-auto max-h-40">
                  {this.state.error.toString()}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}

            <div className="flex gap-2 justify-center">
              <Button
                onClick={this.handleRetry}
                variant="outline"
                size="sm"
                className="flex items-center gap-2"
              >
                <RefreshCw className="h-4 w-4" />
                Try Again
              </Button>
              <Button
                onClick={() => window.location.reload()}
                size="sm"
              >
                Refresh Page
              </Button>
            </div>
          </CardContent>
        </Card>
      );
    }

    return this.props.children;
  }
}

// Functional component wrapper for React hooks
interface FunctionalErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error) => void;
}

export const FunctionalErrorBoundary: React.FC<FunctionalErrorBoundaryProps> = ({
  children,
  fallback,
  onError,
}) => {
  return (
    <ErrorBoundary
      fallback={fallback}
      onError={(error) => {
        if (onError) {
          onError(error);
        }
      }}
    >
      {children}
    </ErrorBoundary>
  );
};

// Specialized error boundaries for specific use cases

export const ChartErrorBoundary: React.FC<{ children: ReactNode }> = ({ children }) => (
  <ErrorBoundary
    fallback={
      <Card className="w-full h-48 flex items-center justify-center border-dashed border-muted-foreground/25">
        <div className="text-center">
          <AlertCircle className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Chart failed to load</p>
          <Button
            onClick={() => window.location.reload()}
            variant="ghost"
            size="sm"
            className="mt-2"
          >
            Reload Chart
          </Button>
        </div>
      </Card>
    }
  >
    {children}
  </ErrorBoundary>
);

export const ApiErrorBoundary: React.FC<{ children: ReactNode; onRetry?: () => void }> = ({
  children,
  onRetry,
}) => (
  <ErrorBoundary
    fallback={
      <Card className="w-full p-4 border-destructive/50">
        <div className="text-center">
          <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-2" />
          <p className="text-sm font-medium mb-1">Data loading failed</p>
          <p className="text-xs text-muted-foreground mb-3">
            There was an error loading the data. Please check your connection.
          </p>
          <Button
            onClick={onRetry || (() => window.location.reload())}
            size="sm"
            variant="outline"
          >
            Retry
          </Button>
        </div>
      </Card>
    }
  >
    {children}
  </ErrorBoundary>
);

export const PageErrorBoundary: React.FC<{ children: ReactNode }> = ({ children }) => (
  <ErrorBoundary
    fallback={
      <div className="min-h-screen flex items-center justify-center">
        <Card className="w-full max-w-lg mx-4">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-4">
              <AlertCircle className="h-16 w-16 text-destructive" />
            </div>
            <CardTitle className="text-xl">Page Error</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p>
              This page encountered an error and couldn't load properly.
            </p>
            <div className="flex gap-2 justify-center">
              <Button
                onClick={() => window.history.back()}
                variant="outline"
              >
                Go Back
              </Button>
              <Button
                onClick={() => window.location.reload()}
              >
                Reload Page
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    }
  >
    {children}
  </ErrorBoundary>
);

// Higher-order component for adding error boundary to any component
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  errorBoundaryProps?: Omit<Props, 'children'>
) {
  const WrappedComponent = (props: P) => (
    <ErrorBoundary {...errorBoundaryProps}>
      <Component {...props} />
    </ErrorBoundary>
  );

  WrappedComponent.displayName = `withErrorBoundary(${Component.displayName || Component.name})`;

  return WrappedComponent;
}
