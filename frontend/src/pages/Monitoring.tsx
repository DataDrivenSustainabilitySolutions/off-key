import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { NavigationBar } from "@/components/NavigationBar";
import { useParams } from "react-router-dom";
import { useFetch } from "@/dataFetch/UseFetch";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import toast from "react-hot-toast";

const Monitoring: React.FC = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  //map where keys and the boolean are safed for the dropbox checked or not checked symbole
  const [visibleMap, setVisibleMap] = useState<Record<string, boolean>>({});
  //Data from useFetch
  const { allTelemetryMap, loadAllTelemetryTypes } = useFetch();
  //Caching mechanism to avoid unneccesary fetches
  const monitoringKeys = useMemo(
    () => {
      const telemetryData = allTelemetryMap[chargerId!] || [];
      return telemetryData.map(item => item.type);
    },
    [allTelemetryMap, chargerId]
  );
  const activeKeys = useMemo(
    () =>
      Object.entries(visibleMap)
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        .filter(([_, visible]) => visible)
        .map(([key]) => key),
    [visibleMap]
  );
  const [selectedAlgorithm, setSelectedAlgorithm] = useState<string | null>(
    null
  );

  // Active services management
  interface ActiveService {
    id: string;
    container_id: string;
    container_name: string;
    mqtt_topics: string[];
    status: boolean;
    created_at?: string;
  }

  const [activeServices, setActiveServices] = useState<ActiveService[]>([]);
  const [isLoadingServices, setIsLoadingServices] = useState(false);

  useEffect(() => {
    if (!chargerId) return;

    loadAllTelemetryTypes(chargerId);
  }, [loadAllTelemetryTypes, chargerId]);

  useEffect(() => {
    if (monitoringKeys.length === 0) return; // if no keys given do nothing
    if (Object.keys(visibleMap).length > 0) return; // if keys already initialised also do nothing
    setVisibleMap(Object.fromEntries(monitoringKeys.map((k) => [k, false]))); //k = keys, bool = should all be shown per default or not

    console.log(visibleMap);
  }, [monitoringKeys, visibleMap]);

  // Load active services
  const loadActiveServices = useCallback(async () => {
    try {
      setIsLoadingServices(true);
      const response = await apiUtils.get(API_CONFIG.ENDPOINTS.MONITORING.LIST);
      setActiveServices(response);
    } catch (error) {
      console.error("Failed to load active services:", error);
      toast.error("Failed to load active services");
    } finally {
      setIsLoadingServices(false);
    }
  }, []);

  // Delete service
  const deleteService = useCallback(async (containerName: string) => {
    if (!confirm(`Are you sure you want to delete the service "${containerName}"?`)) {
      return;
    }

    try {
      await apiUtils.delete(`${API_CONFIG.ENDPOINTS.MONITORING.STOP}?container_name=${encodeURIComponent(containerName)}`);
      toast.success(`Service "${containerName}" deleted successfully`);
      // Refresh the services list
      await loadActiveServices();
    } catch (error) {
      console.error("Failed to delete service:", error);
      toast.error(`Failed to delete service: ${error.message || "Unknown error"}`);
    }
  }, [loadActiveServices]);

  // Extract charger ID from container name (format: radar-{chargerId}-{timestamp})
  const extractChargerIdFromContainer = (containerName: string): string => {
    const match = containerName.match(/^radar-(.+)-\d+$/);
    return match ? match[1] : "Unknown";
  };

  // Filter services to only show ones for the current charger
  const chargerSpecificServices = useMemo(() => {
    if (!chargerId) return [];
    return activeServices.filter(service =>
      extractChargerIdFromContainer(service.container_name) === chargerId
    );
  }, [activeServices, chargerId]);

  // Load services on component mount and set up refresh interval
  useEffect(() => {
    loadActiveServices();

    // Refresh services every 30 seconds
    const interval = setInterval(loadActiveServices, 30000);

    return () => clearInterval(interval);
  }, [loadActiveServices]);

  const submitAnomalyDetection = async () => {
    if (!selectedAlgorithm || activeKeys.length === 0 || !chargerId) {
      alert("Please select at least one sensor and an algorithm.");
      return;
    }

    try {
      // Build MQTT topics using charger ID and selected sensors
      const mqttTopics = activeKeys.map(sensorType => `charger/${chargerId}/${sensorType}`);

      // Generate unique container name
      const containerName = `radar-${chargerId}-${Date.now()}`;

      const response = await apiUtils.post(
        API_CONFIG.ENDPOINTS.MONITORING.START,
        {
          container_name: containerName,
          service_type: "radar",
          mqtt_topics: mqttTopics,
          model_type: selectedAlgorithm,
        }
      );

      console.log("Successfully started monitoring service:", response);
      toast.success(`Monitoring service started successfully! Container: ${containerName}`);
      // Refresh the services list
      await loadActiveServices();
    } catch (error) {
      console.error("Failed to start monitoring service:", error);
      toast.error(`Error: ${error.message || "Failed to start monitoring service"}`);
    }
  };

  return (
    <>
      <NavigationBar />
      <div className="flex mt-5">
        <Card className="ml-16 bg-white shadow-md w-11/12 min-h-11/12 dark:bg-neutral-950">
          <div>
            <CardTitle className="ml-5">
              Monitoring for the Charger {chargerId}
            </CardTitle>
            <CardContent>
              <div className="flex items-start gap-6">
                {/* Left Side */}
                <div className="flex flex-col w-2/5">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button className="w-30 mb-5 mr-3 mt-4 bg-indigo-800 hover:bg-indigo-700 cursor-pointer">
                        Sensor types
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w100">
                      <DropdownMenuLabel>Sensors</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {monitoringKeys.map((key) => (
                        <DropdownMenuCheckboxItem
                          key={key}
                          checked={visibleMap[key]}
                          onCheckedChange={() =>
                            setVisibleMap((prev) => ({
                              ...prev,
                              [key]: !prev[key],
                            }))
                          }
                          onClick={(e) => e.stopPropagation()}
                        >
                          {key}
                        </DropdownMenuCheckboxItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>

                  <div className="mt-6">
                    <h2 className="text-lg font-bold mb-2">
                      Picked values for the Anomaly Detection:
                    </h2>
                    <ul className="list-disc list-inside space-y-1">
                      {activeKeys.map((key) => (
                        <li key={key} className="ml-2">
                          {key}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="h-80 border-l border-gray-300 ml-4 mr-4"></div>
                <div className="flex flex-col w-2/5">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button className="w-30 mt-4 bg-indigo-800 hover:bg-indigo-700 cursor-pointer">
                        Algorithm
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-48">
                      <DropdownMenuCheckboxItem
                        checked={selectedAlgorithm === "isolation_forest"}
                        onCheckedChange={() =>
                          setSelectedAlgorithm("isolation_forest")
                        }
                      >
                        Isolation Forest
                      </DropdownMenuCheckboxItem>
                      <DropdownMenuCheckboxItem
                        checked={selectedAlgorithm === "adaptive_svm"}
                        onCheckedChange={() =>
                          setSelectedAlgorithm("adaptive_svm")
                        }
                      >
                        Adaptive SVM
                      </DropdownMenuCheckboxItem>
                      <DropdownMenuCheckboxItem
                        checked={selectedAlgorithm === "knn"}
                        onCheckedChange={() =>
                          setSelectedAlgorithm("knn")
                        }
                      >
                        K-Nearest Neighbors
                      </DropdownMenuCheckboxItem>
                    </DropdownMenuContent>
                  </DropdownMenu>

                  <div className="mt-10">
                    <h2 className="text-lg font-bold mb-2">
                      Picked Algorithm:
                    </h2>
                    <p>{selectedAlgorithm}</p>
                  </div>
                </div>
              </div>
              <Button
                className="w-30 mt-4 bg-indigo-800 hover:bg-indigo-700 cursor-pointer"
                onClick={submitAnomalyDetection}
              >
                Send
              </Button>
            </CardContent>
          </div>
        </Card>
      </div>

      {/* Active Services Management Section */}
      <div className="flex mt-5">
        <Card className="ml-16 bg-white shadow-md w-11/12 min-h-96 dark:bg-neutral-950">
          <CardTitle className="ml-5 mt-4">Active Monitoring Services for Charger {chargerId}</CardTitle>
          <CardContent>
            <div className="mt-4">
              {isLoadingServices ? (
                <div className="flex justify-center items-center py-8">
                  <div className="text-gray-500">Loading active services...</div>
                </div>
              ) : chargerSpecificServices.length === 0 ? (
                <div className="flex justify-center items-center py-8">
                  <div className="text-gray-500">No active monitoring services found for charger {chargerId}</div>
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
                      {chargerSpecificServices.map((service) => (
                        <TableRow key={service.id}>
                          <TableCell className="font-medium">
                            {service.container_name}
                          </TableCell>
                          <TableCell>
                            {extractChargerIdFromContainer(service.container_name)}
                          </TableCell>
                          <TableCell>
                            <div className="max-w-xs truncate" title={service.mqtt_topics.join(', ')}>
                              {service.mqtt_topics.length > 0
                                ? service.mqtt_topics.slice(0, 2).join(', ') +
                                  (service.mqtt_topics.length > 2 ? ` +${service.mqtt_topics.length - 2} more` : '')
                                : 'No topics'}
                            </div>
                          </TableCell>
                          <TableCell>
                            <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                              service.status
                                ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                                : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                            }`}>
                              {service.status ? 'Active' : 'Inactive'}
                            </span>
                          </TableCell>
                          <TableCell>
                            {service.created_at
                              ? new Date(service.created_at).toLocaleString()
                              : 'Unknown'}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => deleteService(service.container_name)}
                              className="bg-red-600 hover:bg-red-700"
                            >
                              Delete
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
};

export default Monitoring;
