import React from 'react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Loader2, Database, BarChart3 } from 'lucide-react';

const CHART_SKELETON_BAR_HEIGHTS = [
  'h-24',
  'h-32',
  'h-20',
  'h-36',
  'h-28',
  'h-40',
  'h-24',
  'h-44',
  'h-32',
  'h-28',
  'h-36',
  'h-20',
];

// Generic loading skeleton
const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`animate-pulse rounded-lg bg-muted ${className}`}></div>
);

// Chart loading skeleton
export const ChartSkeleton: React.FC = () => (
  <Card className="h-80 w-full">
    <CardHeader>
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-4 w-32" />
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="grid grid-cols-12 gap-2 h-48">
        {CHART_SKELETON_BAR_HEIGHTS.map((barHeight, i) => (
          <div key={i} className="flex flex-col justify-end space-y-1">
            <Skeleton className="h-2 w-full" />
            <Skeleton className={`w-full ${barHeight}`} />
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

// Full page loading
export const FullPageLoading: React.FC<{ message?: string }> = ({
  message = 'Loading...'
}) => (
  <div className="app-canvas flex min-h-screen items-center justify-center">
    <div className="space-y-4 text-center">
      <Loader2 className="animate-spin text-primary h-12 w-12" />
      <p className="text-muted-foreground">{message}</p>
    </div>
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

const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  action,
}) => (
  <Card className="w-full border-dashed bg-card/70 shadow-none">
    <CardContent className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-4 flex size-11 items-center justify-center rounded-xl border border-border/70 bg-muted/45 text-muted-foreground [&_svg]:size-5">
        {icon || <Database />}
      </div>
      <h3 className="mb-2 text-base font-semibold">{title}</h3>
      {description && (
        <p className="mb-4 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p>
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
    icon={<Database />}
    title={message}
    description="Adjust your filters or check back later."
    action={onRefresh ? {
      label: 'Refresh',
      onClick: onRefresh,
    } : undefined}
  />
);

// No charts available
export const NoChartsAvailable: React.FC<{ onRefresh?: () => void }> = ({ onRefresh }) => (
  <EmptyState
    icon={<BarChart3 />}
    title="No chart data available"
    description="No telemetry available yet."
    action={onRefresh ? {
      label: 'Try Again',
      onClick: onRefresh,
    } : undefined}
  />
);
