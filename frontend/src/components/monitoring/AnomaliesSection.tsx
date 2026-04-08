/**
 * AnomaliesSection Component
 *
 * Displays detected anomalies for a charger with severity indicators
 * and refresh capability.
 */

import React from "react";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Anomaly } from "@/types/charger";
import { getAnomalyTailProbabilityClassName, formatAnomalyTailProbability } from "@/lib/anomaly-semantics";

interface AnomaliesSectionProps {
  anomalies: Anomaly[];
  isLoading: boolean;
  chargerId?: string;
  onRefresh: () => void;
}

// Max anomalies to display in the table
const MAX_DISPLAYED_ANOMALIES = 50;

export const AnomaliesSection: React.FC<AnomaliesSectionProps> = ({
  anomalies,
  isLoading,
  chargerId,
  onRefresh,
}) => (
  <div className="flex mt-5 mb-5">
    <Card className="ml-16 bg-white shadow-md w-11/12 min-h-96 dark:bg-neutral-950">
      <CardTitle className="ml-5 mt-4">
        Detected Anomalies for Charger {chargerId}
      </CardTitle>
      <CardContent>
        <div className="mt-4">
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-gray-500">
              {anomalies.length} anomalies detected
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={isLoading}
            >
              {isLoading ? "Refreshing..." : "Refresh"}
            </Button>
          </div>

          {isLoading ? (
            <div className="flex justify-center items-center py-8">
              <div className="text-gray-500">Loading anomalies...</div>
            </div>
          ) : anomalies.length === 0 ? (
            <div className="flex justify-center items-center py-8">
              <div className="text-gray-500">
                No anomalies detected for charger {chargerId}
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Telemetry Type</TableHead>
                    <TableHead>Anomaly Type</TableHead>
                    <TableHead>Score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {anomalies
                    .slice(0, MAX_DISPLAYED_ANOMALIES)
                    .map((anomaly, index) => (
                      <TableRow key={`${anomaly.timestamp}-${index}`}>
                        <TableCell className="font-medium">
                          {new Date(anomaly.timestamp).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <span className="px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                            {anomaly.telemetry_type}
                          </span>
                        </TableCell>
                        <TableCell>{anomaly.anomaly_type}</TableCell>
                        <TableCell>
                          {anomaly.value_type === 'tail_pvalue' ? (
                            <span
                              className={`px-2 py-1 rounded-full text-xs font-medium ${getAnomalyTailProbabilityClassName(
                                anomaly.anomaly_value
                              )}`}
                            >
                              {formatAnomalyTailProbability(anomaly.anomaly_value)}
                            </span>
                          ) : (
                            <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                              {anomaly.anomaly_value.toFixed(2)} (legacy)
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
              {anomalies.length > MAX_DISPLAYED_ANOMALIES && (
                <div className="text-center py-2 text-sm text-gray-500">
                  Showing {MAX_DISPLAYED_ANOMALIES} of {anomalies.length}{" "}
                  anomalies
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  </div>
);

export default AnomaliesSection;
