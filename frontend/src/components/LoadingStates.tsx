import React from 'react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Loader2, Database, BarChart3, AlertCircle, RefreshCw, Wifi } from 'lucide-react';

// Generic loading skeleton
export const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`animate-pulse bg-muted rounded ${className}`}></div>
);

// Chart loading skeleton
export const ChartSkeleton: React.FC = () => (
  <Card className="w-full h-80">
    <CardHeader>
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-4 w-32" />
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="grid grid-cols-12 gap-2 h-48">
        {[...Array(12)].map((_, i) => (
          <div key={i} className="flex flex-col justify-end space-y-1">
            <Skeleton className="h-2 w-full" />
            <Skeleton className={`w-full h-${Math.floor(Math.random() * 20) + 10}`} />
          </div>
        ))}
      </div>
      <div className="flex space-x-4">
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-24" />
      </div>
    </CardContent>
  </Card>
);

// Table loading skeleton
export const TableSkeleton: React.FC<{ rows?: number; cols?: number }> = ({
  rows = 5,
  cols = 4
}) => (
  <Card>
    <CardContent className="pt-6">
      <div className="space-y-3">
        <div className="grid grid-cols-4 gap-4">
          {[...Array(cols)].map((_, i) => (
            <Skeleton key={i} className="h-4" />
          ))}
        </div>
        {[...Array(rows)].map((_, i) => (
          <div key={i} className="grid grid-cols-4 gap-4">
            {[...Array(cols)].map((_, j) => (
              <Skeleton key={j} className="h-4" />
            ))}
          </div>
        ))}
      </div>
    </CardContent>
  </Card>
);

// Card loading skeleton
export const CardSkeleton: React.FC = () => (
  <Card>
    <CardHeader>
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
    </CardHeader>
    <CardContent className="space-y-4">
      <Skeleton className="h-20 w-full" />
      <div className="flex space-x-2">
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-8 w-16" />
      </div>
    </CardContent>
  </Card>
);

// List loading skeleton
export const ListSkeleton: React.FC<{ items?: number }> = ({ items = 5 }) => (
  <div className="space-y-3">
    {[...Array(items)].map((_, i) => (
      <Card key={i}>
        <CardContent className="p-4">
          <div className="flex items-center space-x-4">
            <Skeleton className="h-10 w-10 rounded-full" />
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
            <Skeleton className="h-6 w-16" />
          </div>
        </CardContent>
      </Card>
    ))}
  </div>
);

// Loading spinner
export const LoadingSpinner: React.FC<{
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}> = ({ size = 'md', className = '' }) => {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  };

  return (
    <Loader2 className={`animate-spin ${sizeClasses[size]} ${className}`} />
  );
};

// Full page loading
export const FullPageLoading: React.FC<{ message?: string }> = ({
  message = 'Loading...'
}) => (
  <div className="min-h-screen flex items-center justify-center">
    <div className="text-center space-y-4">
      <LoadingSpinner size="lg" />
      <p className="text-muted-foreground">{message}</p>
    </div>
  </div>
);

// Inline loading
export const InlineLoading: React.FC<{ message?: string }> = ({
  message = 'Loading...'
}) => (
  <div className="flex items-center justify-center space-x-2 py-8">
    <LoadingSpinner size="sm" />
    <span className="text-sm text-muted-foreground">{message}</span>
  </div>
);

// EMPTY STATES

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  action,
}) => (
  <Card className="w-full">
    <CardContent className="flex flex-col items-center justify-center py-12 text-center">
      <div className="mb-4 text-muted-foreground">
        {icon || <Database className="h-12 w-12" />}
      </div>
      <h3 className="text-lg font-semibold mb-2">{title}</h3>
      {description && (
        <p className="text-muted-foreground mb-4 max-w-sm">{description}</p>
      )}
      {action && (
        <Button onClick={action.onClick} variant="outline">
          {action.label}
        </Button>
      )}
    </CardContent>
  </Card>
);

// No data found
export const NoDataFound: React.FC<{
  message?: string;
  onRefresh?: () => void;
}> = ({
  message = 'No data found',
  onRefresh
}) => (
  <EmptyState
    icon={<Database className="h-12 w-12" />}
    title={message}
    description="There's no data available for the selected criteria. Try adjusting your filters or check back later."
    action={onRefresh ? {
      label: 'Refresh',
      onClick: onRefresh,
    } : undefined}
  />
);

// No anomalies found
export const NoAnomaliesFound: React.FC<{ onRefresh?: () => void }> = ({ onRefresh }) => (
  <EmptyState
    icon={<AlertCircle className="h-12 w-12" />}
    title="No anomalies detected"
    description="No anomalies have been detected for the selected time period. This is good news!"
    action={onRefresh ? {
      label: 'Refresh Data',
      onClick: onRefresh,
    } : undefined}
  />
);

// No charts available
export const NoChartsAvailable: React.FC<{ onRefresh?: () => void }> = ({ onRefresh }) => (
  <EmptyState
    icon={<BarChart3 className="h-12 w-12" />}
    title="No chart data available"
    description="Unable to display charts. Data may still be loading or unavailable."
    action={onRefresh ? {
      label: 'Try Again',
      onClick: onRefresh,
    } : undefined}
  />
);

// Connection error
export const ConnectionError: React.FC<{ onRetry?: () => void }> = ({ onRetry }) => (
  <EmptyState
    icon={<Wifi className="h-12 w-12" />}
    title="Connection error"
    description="Unable to connect to the server. Please check your internet connection and try again."
    action={onRetry ? {
      label: 'Retry Connection',
      onClick: onRetry,
    } : undefined}
  />
);

// Search empty state
export const NoSearchResults: React.FC<{
  searchTerm: string;
  onClearSearch?: () => void;
}> = ({ searchTerm, onClearSearch }) => (
  <EmptyState
    title="No results found"
    description={`No results found for "${searchTerm}". Try different keywords or clear your search.`}
    action={onClearSearch ? {
      label: 'Clear Search',
      onClick: onClearSearch,
    } : undefined}
  />
);

// Data refresh state
export const DataRefreshState: React.FC<{
  lastUpdated?: Date;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}> = ({ lastUpdated, onRefresh, isRefreshing }) => (
  <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
    <div className="text-sm text-muted-foreground">
      {lastUpdated ? (
        `Last updated: ${lastUpdated.toLocaleTimeString()}`
      ) : (
        'Data not loaded'
      )}
    </div>
    {onRefresh && (
      <Button
        onClick={onRefresh}
        disabled={isRefreshing}
        size="sm"
        variant="outline"
        className="flex items-center gap-2"
      >
        <RefreshCw className={`h-3 w-3 ${isRefreshing ? 'animate-spin' : ''}`} />
        {isRefreshing ? 'Refreshing...' : 'Refresh'}
      </Button>
    )}
  </div>
);
