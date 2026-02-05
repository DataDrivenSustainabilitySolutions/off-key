/**
 * ActiveServicesSection Component
 *
 * Displays active monitoring services (RADAR containers) with
 * their status, topics, and management actions.
 */

import React, { useMemo } from "react";
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
import type { ActiveService } from "@/types/monitoring";
import { getStatusDisplay } from "@/types/monitoring";

interface ActiveServicesSectionProps {
  services: ActiveService[];
  isLoading: boolean;
  chargerId?: string;
  onDelete: (containerName: string) => void | Promise<void>;
}

/**
 * Extract charger ID from container name
 * Expected format: radar-<charger_id>-<timestamp>
 */
const extractChargerIdFromContainer = (containerName: string): string => {
  const match = containerName.match(/^radar-(.+)-\d+$/);
  return match ? match[1] : "Unknown";
};

export const ActiveServicesSection: React.FC<ActiveServicesSectionProps> = ({
  services,
  isLoading,
  chargerId,
  onDelete,
}) => {
  // Filter services for the current charger
  const chargerSpecificServices = useMemo(() => {
    if (!chargerId) return services;
    return services.filter(
      (service) =>
        extractChargerIdFromContainer(service.container_name) === chargerId
    );
  }, [services, chargerId]);

  return (
    <div className="flex mt-5">
      <Card className="ml-16 bg-white shadow-md w-11/12 min-h-96 dark:bg-neutral-950">
        <CardTitle className="ml-5 mt-4">
          Active Monitoring Services for Charger {chargerId}
        </CardTitle>
        <CardContent>
          <div className="mt-4">
            {isLoading ? (
              <div className="flex justify-center items-center py-8">
                <div className="text-gray-500">Loading active services...</div>
              </div>
            ) : chargerSpecificServices.length === 0 ? (
              <div className="flex justify-center items-center py-8">
                <div className="text-gray-500">
                  No active monitoring services found for charger {chargerId}
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Container Name</TableHead>
                      <TableHead>Charger ID</TableHead>
                      <TableHead>MQTT Topics</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created At</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {chargerSpecificServices.map((service) => {
                      const statusDisplay = getStatusDisplay(
                        service.docker_status,
                        service.status
                      );

                      return (
                        <TableRow key={service.id}>
                          <TableCell className="font-medium">
                            {service.container_name}
                          </TableCell>
                          <TableCell>
                            {extractChargerIdFromContainer(
                              service.container_name
                            )}
                          </TableCell>
                          <TableCell>
                            <div
                              className="max-w-xs truncate"
                              title={service.mqtt_topics.join(", ")}
                            >
                              {service.mqtt_topics.length > 0
                                ? service.mqtt_topics.slice(0, 2).join(", ") +
                                  (service.mqtt_topics.length > 2
                                    ? ` +${service.mqtt_topics.length - 2} more`
                                    : "")
                                : "No topics"}
                            </div>
                          </TableCell>
                          <TableCell>
                            <span
                              className={`px-2 py-1 rounded-full text-xs font-medium ${statusDisplay.className}`}
                            >
                              {statusDisplay.label}
                            </span>
                          </TableCell>
                          <TableCell>
                            {service.created_at
                              ? new Date(service.created_at).toLocaleString()
                              : "Unknown"}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => onDelete(service.container_name)}
                              className="bg-red-600 hover:bg-red-700"
                            >
                              Delete
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ActiveServicesSection;
