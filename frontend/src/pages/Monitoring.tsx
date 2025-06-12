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

  useEffect(() => {
    if (!chargerId) return;

    loadMonitoring(chargerId);
  }, [loadMonitoring, chargerId]);

  useEffect(() => {
    if (monitoringKeys.length === 0) return; // if no keys given do nothing
    if (Object.keys(visibleMap).length > 0) return; // if keys already initialised also do nothing
    setVisibleMap(Object.fromEntries(monitoringKeys.map((k) => [k, true]))); //k = keys, bool = should all be shown per default or not

    console.log(visibleMap);
  }, [monitoringKeys, visibleMap]);
  return (
    <>
      <NavigationBar />
      <div className="flex mt-5">
        <Card className="ml-16 bg-white shadow-md w-11/12 min-h-11/12 dark:bg-neutral-950">
          <div>
            <CardTitle className="ml-5">
              Monitoring für Charger {chargerId}
            </CardTitle>
            <CardContent>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button className="mb-5 mr-3 mt-4 bg-indigo-800 hover:bg-indigo-700 cursor-pointer">
                    Sensortypen
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w100">
                  <DropdownMenuLabel>Sensoren</DropdownMenuLabel>
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

              <div className="mt-4 space-y-2">
                {monitoringKeys.map(
                  (key) =>
                    visibleMap[key] && (
                      <div key={key} className="p-2 border rounded">
                        <span className="font-semibold">{key}</span>:{" "}
                        {monitoringMap[key]?.length
                          ? monitoringMap[key][0].value != null
                            ? monitoringMap[key][0].value
                            : "Der Schlüssel hat noch keinen Wert"
                          : "Der Schlüssel hat noch keinen Wert"}
                      </div>
                    )
                )}
              </div>
            </CardContent>
          </div>
        </Card>
      </div>
    </>
  );
};

export default Monitoring;
