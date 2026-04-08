import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { useState, useEffect, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { NavigationBar } from "@/components/NavigationBar";
import { useFetch } from "@/dataFetch/UseFetch";
import { ChartSkeleton, NoDataFound } from "@/components/LoadingStates";
import DynamicTelemetryChart from "@/components/DynamicTelemetryChart";
import { Button } from "@/components/ui/button";
import { INTERVALS } from "@/lib/constants";
import { clientLogger } from "@/lib/logger";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const Details: React.FC = () => {
  const { chargerId } = useParams<{ chargerId: string }>();

  // Import functions and data from FetchContext
  const {
    allTelemetryMap,
    anomaliesMap,
    loadAllTelemetryTypes,
    loadAnomalies,
    syncTelemetryShort,
  } = useFetch();

  // Loading states
  const [isLoadingTelemetry, setIsLoadingTelemetry] = useState(true);

  // Fetch dynamic telemetry data and anomalies
  useEffect(() => {
    if (!chargerId) return;

    // Load initial data with loading state tracking
    const loadInitialData = async () => {
      setIsLoadingTelemetry(true);

      try {
        await Promise.all([
          loadAllTelemetryTypes(chargerId).finally(() => setIsLoadingTelemetry(false)),
          loadAnomalies(chargerId),
        ]);
      } catch (error) {
        clientLogger.error({
          event: "details.initial_load_failed",
          message: "Error loading initial details data",
          error,
          context: { chargerId },
        });
        setIsLoadingTelemetry(false);
      }
    };

    loadInitialData();

    const interval = setInterval(() => {
      syncTelemetryShort();
      loadAllTelemetryTypes(chargerId);
      loadAnomalies(chargerId);
    }, INTERVALS.DETAILS_UPDATE); // every 10s

    // Cleanup on unmount or change
    return () => clearInterval(interval);
  }, [chargerId, syncTelemetryShort, loadAllTelemetryTypes, loadAnomalies]);

  // Get dynamic telemetry data and anomalies
  const allTelemetryData = allTelemetryMap[chargerId!] || [];
  const chargerAnomalies = anomaliesMap[chargerId!] || [];

  // Group telemetry data by category for better organization
  const telemetryByCategory = useMemo(() => {
    const grouped = {
      cpu: [] as typeof allTelemetryData,
      system: [] as typeof allTelemetryData,
      controller: [] as typeof allTelemetryData,
      other: [] as typeof allTelemetryData,
    };

    allTelemetryData.forEach(telemetry => {
      grouped[telemetry.category].push(telemetry);
    });

    return grouped;
  }, [allTelemetryData]);


  // No additional functions needed - all functionality is handled by DynamicTelemetryChart

  return (
    <>
      <NavigationBar />
      <div className="flex mt-5">
        <Card className="ml-16 bg-white shadow-md w-11/12 min-h-11/12 dark:bg-neutral-950">
          <CardTitle className="ml-5">Charger {chargerId}</CardTitle>
          <CardContent>
            <Link to={`/monitoring/${chargerId}`}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button className="mb-5 mr-3 float-right bg-indigo-800 hover:bg-indigo-700 cursor-pointer">
                    Monitoring
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top" align="center">
                  Open Live Monitoring
                </TooltipContent>
              </Tooltip>
            </Link>


            {/* Future: Add summary cards here if needed */}

            {/* Dynamic Telemetry Charts */}
            {isLoadingTelemetry ? (
              <div className="space-y-4">
                <ChartSkeleton />
                <ChartSkeleton />
              </div>
            ) : allTelemetryData.length === 0 ? (
              <div className="h-80">
                <NoDataFound
                  message="No telemetry data available for this charger"
                  onRefresh={() => {
                    setIsLoadingTelemetry(true);
                    loadAllTelemetryTypes(chargerId!).finally(() => setIsLoadingTelemetry(false));
                  }}
                />
              </div>
            ) : (
              <div className="space-y-4">
                {/* CPU Category Charts */}
                {telemetryByCategory.cpu.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-2">CPU Metrics</h3>
                    {telemetryByCategory.cpu.map((telemetryData) => (
                      <DynamicTelemetryChart
                        key={telemetryData.type}
                        telemetryData={telemetryData}
                        chargerId={chargerId!}
                        anomalies={chargerAnomalies}
                      />
                    ))}
                  </div>
                )}

                {/* System Category Charts */}
                {telemetryByCategory.system.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-2">System Metrics</h3>
                    {telemetryByCategory.system.map((telemetryData) => (
                      <DynamicTelemetryChart
                        key={telemetryData.type}
                        telemetryData={telemetryData}
                        chargerId={chargerId!}
                        anomalies={chargerAnomalies}
                      />
                    ))}
                  </div>
                )}

                {/* Controller Category Charts */}
                {telemetryByCategory.controller.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-2">Controller Metrics</h3>
                    {telemetryByCategory.controller.map((telemetryData) => (
                      <DynamicTelemetryChart
                        key={telemetryData.type}
                        telemetryData={telemetryData}
                        chargerId={chargerId!}
                        anomalies={chargerAnomalies}
                      />
                    ))}
                  </div>
                )}

                {/* Other Category Charts */}
                {telemetryByCategory.other.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-2">Other Metrics</h3>
                    {telemetryByCategory.other.map((telemetryData) => (
                      <DynamicTelemetryChart
                        key={telemetryData.type}
                        telemetryData={telemetryData}
                        chargerId={chargerId!}
                        anomalies={chargerAnomalies}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card >
      </div >
    </>
  );
};
export default Details;
