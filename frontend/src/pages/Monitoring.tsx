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
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

const Monitoring: React.FC = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  //map where keys and the boolean are safed for the dropbox checked or not checked symbole
  const [visibleMap, setVisibleMap] = useState<Record<string, boolean>>({});
  //Data from useFetch
  const { monitoringMap, loadMonitoring } = useFetch();
  //Caching mechanism to avoid unneccesary fetches
  const monitoringKeys = useMemo(
    () => Object.keys(monitoringMap),
    [monitoringMap]
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

  useEffect(() => {
    if (!chargerId) return;

    loadMonitoring(chargerId);
  }, [loadMonitoring, chargerId]);

  useEffect(() => {
    if (monitoringKeys.length === 0) return; // if no keys given do nothing
    if (Object.keys(visibleMap).length > 0) return; // if keys already initialised also do nothing
    setVisibleMap(Object.fromEntries(monitoringKeys.map((k) => [k, false]))); //k = keys, bool = should all be shown per default or not

    console.log(visibleMap);
  }, [monitoringKeys, visibleMap]);

  const submitAnomalyDetection = async () => {
    if (!selectedAlgorithm || activeKeys.length === 0) {
      alert("Please select at least one sensor and an algorithm.");
      return;
    }
    try {
      const response = await axios.post(
        `http://127.0.0.1:8000/v1/anomalyDetection/`,
        {
          chargerId,
          selectedAlgorithm,
          selectedSensors: activeKeys,
        }
      );

      console.log("Successfully submitted:", response.data);
    } catch (error) {
      console.error("Failed to submit configuration:", error);
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
                {/* Linke Seite */}
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
                        checked={selectedAlgorithm === "Algorithm A"}
                        onCheckedChange={() =>
                          setSelectedAlgorithm("Algorithm A")
                        }
                      >
                        Algorithm A
                      </DropdownMenuCheckboxItem>
                      <DropdownMenuCheckboxItem
                        checked={selectedAlgorithm === "Algorithm B"}
                        onCheckedChange={() =>
                          setSelectedAlgorithm("Algorithm B")
                        }
                      >
                        Algorithm B
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
    </>
  );
};

export default Monitoring;
