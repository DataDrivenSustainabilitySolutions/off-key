import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useRedZones } from "../lib/useRedZones";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceArea,
  // PieChart,
  // Pie,
  // Cell,
  // BarChart,
  // Bar,
  // Rectangle,
} from "recharts";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { format } from "date-fns";
import { Popover } from "@/components/ui/popover";
import { NavigationBar } from "@/components/NavigationBar";

// import {
//   Table,
//   TableBody,
//   TableCaption,
//   TableCell,
//   TableHead,
//   TableHeader,
//   TableRow,
// } from "@/components/ui/table";

//interface for CPU USage and Thermal
interface Cpu {
  timestamp: string;
  value: number;
}

const Details: React.FC = () => {
  const [collapsedCard, setCollapsedCard] = useState<Record<string, boolean>>({
    smallCard1: false,
    smallCard2: false,
    smallCard3: false,
    CpuUsageCard: false,
    CpuThermalCard: false,
  });
  const [, setSearchError] = useState(false);
  const { charger_id } = useParams();
  const [controllerCpuUsageKey, setControllerCpuUsageKey] = useState<string>();
  const [
    controllertemperaturecpu_thermalKey,
    setControllertemperaturecpu_thermalKey,
  ] = useState<string>();
  const [fromDateUsage, setFromDateUsage] = useState<Date>();
  const [fromDateThermal, setFromDateThermal] = useState<Date>();
  const [toDateUsage, setToDateUsage] = useState<Date>();
  const [toDateThermal, setToDateThermal] = useState<Date>();
  const [controllerCpuUsageData, setControllerCpuUsageData] = useState<Cpu[]>(
    []
  );
  const [
    controllertemperaturecpu_thermalData,
    setControllertemperaturecpu_thermalData,
  ] = useState<Cpu[]>([]);
  //redZones in the Diagram Params: 1. Dataarray, 2. value where the Zone gets red
  const redZonesCpuUsage = useRedZones(controllerCpuUsageData, 7);
  const redZonesCpuThermal = useRedZones(
    controllertemperaturecpu_thermalData,
    43
  );
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 1) only at mount or when charger_id is changing: get Telemetry types
  useEffect(() => {
    if (!charger_id) return;

    async function getTelemetryTypes() {
      try {
        const response = await axios.get(
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/type`
        );
        const results: string[] = response.data;
        // Search in results for the 2 CPU Keys
        const cpuUsageKey = results.find(
          (t) => t.toLowerCase() === "controllercpuusage"
        );
        const cpuThermalKey = results.find(
          (t) => t.toLowerCase() === "controllertemperaturecpu-thermal"
        );

        if (cpuUsageKey && cpuThermalKey) {
          setControllerCpuUsageKey(cpuUsageKey);
          setControllertemperaturecpu_thermalKey(cpuThermalKey);
          setSearchError(false);
        } else {
          console.warn(
            "Telemetrie-Keys nicht gefunden:",
            { cpuUsageKey, cpuThermalKey },
            "in",
            results
          );
          setSearchError(true);
        }
      } catch (error) {
        console.error("Fehler beim Laden der Telemetrie-Typen:", error);
        setSearchError(true);
      }
    }

    getTelemetryTypes();
  }, [charger_id]);

  // 2) after charger_id, controllerCpuUsage and controllertemperaturecpu_thermal are set up:
  // first fetch then every 20 seconds repeat
  useEffect(() => {
    if (
      !charger_id ||
      !controllerCpuUsageKey ||
      !controllertemperaturecpu_thermalKey
    ) {
      return;
    }

    async function fetchTelemetryData() {
      try {
        // CPU Usage
        const respUsage = await axios.get(
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/${controllerCpuUsageKey}?limit=1000`
        );
        setControllerCpuUsageData(respUsage.data);
        console.log("CPU Usage:", respUsage.data);

        // CPU Thermal
        const respThermal = await axios.get(
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/${controllertemperaturecpu_thermalKey}?limit=1000`
        );
        setControllertemperaturecpu_thermalData(respThermal.data);
        console.log("CPU Thermal:", respThermal.data);
      } catch (error) {
        console.error("Fehler beim Daten-Fetch:", error);
        setSearchError(true);
      }
    }

    // initial fetch
    fetchTelemetryData();

    //Datafetch every 20 seconds
    intervalRef.current = setInterval(fetchTelemetryData, 20000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [charger_id, controllerCpuUsageKey, controllertemperaturecpu_thermalKey]);

  //Function to minimize the Cards
  const minimizeCards = (key: string) => {
    setCollapsedCard((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  //Function to format the Timestamps from the Time Rows
  const formatDateMultiline = (value: string) => {
    const date = new Date(value);
    const day = String(date.getDate()).padStart(2, "0");
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const hour = String(date.getHours()).padStart(2, "0");
    const minute = String(date.getMinutes()).padStart(2, "0");
    const second = String(date.getSeconds()).padStart(2, "0");
    return `${day}.${month}, ${hour}:${minute}:${second}`;
  };

  //function to filter the Cpu Usage with the Dates the user selected in the Navbar for the Diagram
  const filteredDataCpuUsage = controllerCpuUsageData.filter((cpu) => {
    const t = new Date(cpu.timestamp).getTime();
    const f = fromDateUsage?.getTime() ?? -Infinity;
    const u = toDateUsage?.getTime() ?? Infinity;
    return t >= f && t <= u;
  });

  //function to filter the Cpu Thermal with the Dates the user selected in the Navbar for the Diagram
  const filteredDataCpuThermal = controllertemperaturecpu_thermalData.filter(
    (d) => {
      const t = new Date(d.timestamp).getTime();
      const f = fromDateThermal?.getTime() ?? -Infinity;
      const u = toDateThermal?.getTime() ?? Infinity;
      return t >= f && t <= u;
    }
  );
  //function for the buttons to handle last minute and last 10 minuts for CPU Usage and Thermal
  function handleLastMinutes(
    dataArray: Cpu[],
    setFrom: React.Dispatch<React.SetStateAction<Date | undefined>>,
    setTo: React.Dispatch<React.SetStateAction<Date | undefined>>,
    minutes: number
  ) {
    if (dataArray.length === 0) return;
    const times = dataArray.map((d) => new Date(d.timestamp).getTime());
    const maxTime = Math.max(...times);
    const minTime = maxTime - minutes * 60 * 1000;
    setFrom(new Date(minTime));
    setTo(new Date(maxTime));
  }
  // Use this for last 30 minutes Button in the Usage Card - change the number for another timespan in minutes
  const usageLast30Min = () =>
    handleLastMinutes(
      controllerCpuUsageData,
      setFromDateUsage,
      setToDateUsage,
      30
    );
  // Use this for last Hour Button in the Usage Card - change the number for another timespan in minutes
  const usageLastHour = () =>
    handleLastMinutes(
      controllerCpuUsageData,
      setFromDateUsage,
      setToDateUsage,
      60
    );
  // Use this for last 30 minutes Button in the thermal Card - change the number for another timespan in minutes
  const thermalLast30Min = () =>
    handleLastMinutes(
      controllertemperaturecpu_thermalData,
      setFromDateThermal,
      setToDateThermal,
      30
    );
  // Use this for last Hour Button in the Thermal Card - change the number for another timespan in minutes
  const thermalLastHour = () =>
    handleLastMinutes(
      controllertemperaturecpu_thermalData,
      setFromDateThermal,
      setToDateThermal,
      60
    );

  return (
    <>
      <NavigationBar />
      <div className="flex mt-5">
        <Card className="ml-16 bg-white shadow-md w-11/12 min-h-11/12 dark:bg-neutral-950">
          <CardTitle className="ml-5">Charger {charger_id}</CardTitle>
          <CardContent>
            <div className="flex justify-between">
              {/* Short Info Cards
              /* <Card
      className={`transition-all duration-300 w-70 ${
        collapsedCard.card1 ? "h-16" : "h-70"
      }`}
    >
      <div className="flex justify-between">
        <CardTitle className="ml-5">Activity </CardTitle>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
          onClick={() => minimizeCards("card1")}
          className={`size-6 mr-5 cursor-pointer transition-transform ${
            collapsedCard.card1 ? "rotate-180" : ""
          }`}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m19.5 8.25-7.5 7.5-7.5-7.5"
          />
        </svg>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            dataKey="value"
            data={pieData}
            cx="50%"
            cy="50%"
            innerRadius={40}
            outerRadius={80}
          >
            {pieData.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.name === "online" ? "#82ca9d" : "#f87171"}
              />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </Card>
    <Card
      className={`transition-all duration-300 w-70 ${
        collapsedCard.card2 ? "h-16" : "h-70"
      }`}
    >
      <div className="flex justify-between">
        <CardTitle className="ml-5">Usage Count per Day</CardTitle>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
          onClick={() => minimizeCards("card2")}
          className={`size-6 mr-5 cursor-pointer transition-transform ${
            collapsedCard.card2 ? "rotate-180" : ""
          }`}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m19.5 8.25-7.5 7.5-7.5-7.5"
          />
        </svg>
      </div>

      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={barData}
          margin={{
            top: 20,
            right: 50,
            bottom: 5,
          }}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="Day" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar
            dataKey="UsageCount"
            fill="#8884d8"
            activeBar={<Rectangle fill="pink" stroke="blue" />}
          />
        </BarChart>
      </ResponsiveContainer>
    </Card>
    <Card
      className={`transition-all duration-300 w-70 ${
        collapsedCard.card3 ? "h-16" : "h-70"
      }`}
    >
      <div className="flex justify-between">
        <CardTitle className="ml-5">CPU Stats </CardTitle>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
          onClick={() => minimizeCards("card3")}
          className={`size-6 mr-5 cursor-pointer transition-transform ${
            collapsedCard.card3 ? "rotate-180" : ""
          }`}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m19.5 8.25-7.5 7.5-7.5-7.5"
          />
        </svg>
      </div>
      <Table>
        <TableCaption>
          Shows the Today's Lowest and Peaks of the CPU Stats like Usage
          and Temperature
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[100px]"></TableHead>
            <TableHead>Lowest</TableHead>
            <TableHead>Peak</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell className="font-medium">Usage %</TableCell>
            <TableCell>45 %</TableCell>
            <TableCell>78 %</TableCell>
          </TableRow>
          <TableRow>
            <TableCell className="font-medium">Temp °C</TableCell>
            <TableCell>20°C</TableCell>
            <TableCell>55°C</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Card> */}
            </div>

            <Card
              className={`mr-6 w-full mb-4 transition-all duration-300 overflow-hidden ${
                collapsedCard.CpuUsageCard ? "h-16" : "h-96"
              }`}
            >
              <div className="flex justify-between">
                <CardTitle className="ml-5">CPU Usage</CardTitle>
                {!collapsedCard.CpuUsageCard && (
                  <div className="flex">
                    <Popover>
                      <div className="relative">
                        <Input
                          type="datetime-local"
                          className="cursor-pointer"
                          placeholder="Von"
                          value={
                            fromDateUsage
                              ? format(fromDateUsage, "yyyy-MM-dd'T'HH:mm")
                              : ""
                          }
                          //empty field befor input for reload
                          onFocus={() => setFromDateUsage(undefined)}
                          onChange={(e) => {
                            const value = e.currentTarget.value;
                            setFromDateUsage(
                              value ? new Date(value) : undefined
                            );
                          }}
                        />
                      </div>
                    </Popover>
                    <h2 className="ml-3 mr-3 text-2xl font-semibold tracking-tight transition-colors first:mt-0">
                      :
                    </h2>
                    <Popover>
                      <div className="relative">
                        <Input
                          type="datetime-local"
                          className="cursor-pointer"
                          placeholder="Bis"
                          value={
                            toDateUsage
                              ? format(toDateUsage, "yyyy-MM-dd'T'HH:mm")
                              : ""
                          }
                          //empty field befor input for reload
                          onFocus={() => setToDateUsage(undefined)}
                          onChange={(e) => {
                            const value = e.target.value;
                            setToDateUsage(value ? new Date(value) : undefined);
                          }}
                        />
                      </div>
                    </Popover>
                    <div>
                      <div className="flex items-center h-9 ml-5 space-x-2 rounded-lg border bg-white px-3  dark:bg-transparent">
                        <button
                          onClick={usageLast30Min}
                          className="text-sm text-gray-700 hover:underline focus:outline-none dark:text-white"
                        >
                          last 30 Minutes
                        </button>
                        <div className="h-6 border-l border-gray-300 mx-2 " />
                        <button
                          onClick={usageLastHour}
                          className="text-sm text-gray-700 hover:underline focus:outline-none dark:text-white"
                        >
                          last Hour
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                  onClick={() => minimizeCards("CpuUsageCard")}
                  className={`size-6 mr-5 cursor-pointer transition-transform" ${
                    collapsedCard.CpuUsageCard ? "rotate-180" : ""
                  }`}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </div>
              {!collapsedCard.CpuUsageCard && (
                <ResponsiveContainer width="90%" height="90%">
                  <LineChart
                    width={500}
                    height={300}
                    data={filteredDataCpuUsage.slice().reverse()}
                    margin={{
                      top: 5,
                      right: 30,
                      left: 20,
                      bottom: 5,
                    }}
                  >
                    <CartesianGrid strokeDasharray="5 5" />
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={formatDateMultiline}
                    />

                    <YAxis dataKey="value" />
                    <Tooltip />
                    <Legend />
                    {redZonesCpuUsage.map((zone, index) => (
                      <ReferenceArea
                        key={index}
                        x1={zone.start}
                        x2={zone.end}
                        strokeOpacity={0}
                        fill="red"
                        fillOpacity={0.1}
                      />
                    ))}
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="#8884d8"
                      activeDot={false}
                      dot={({ cx, cy, payload }) => {
                        const border = payload.value >= 7;
                        return (
                          <circle
                            key={`dot-${payload.timestamp}`}
                            cx={cx}
                            cy={cy}
                            //if value is above the border dots geting 0 radius so they are invisible else they are red
                            r={border ? 2 : 0}
                            fill={border ? "red" : "transparent"}
                            stroke="none"
                          />
                        );
                      }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Card>
            <Card
              className={` w-full transition-all duration-300 overflow-hidden ${
                collapsedCard.CpuThermalCard ? "h-16" : "h-96"
              }`}
            >
              <div className="flex justify-between">
                <CardTitle className="ml-5">CPU Thermal</CardTitle>
                {!collapsedCard.CpuThermalCard && (
                  <div className="flex">
                    <Popover>
                      <div className="relative">
                        <Input
                          type="datetime-local"
                          className="cursor-pointer"
                          placeholder="Von"
                          value={
                            fromDateThermal
                              ? format(fromDateThermal, "yyyy-MM-dd'T'HH:mm")
                              : ""
                          }
                          //empty field befor input for reload
                          onFocus={() => setFromDateThermal(undefined)}
                          onChange={(e) => {
                            const value = e.target.value;
                            setFromDateThermal(
                              value ? new Date(value) : undefined
                            );
                          }}
                        />
                      </div>
                    </Popover>
                    <h2 className="ml-3 mr-3 text-2xl font-semibold tracking-tight transition-colors first:mt-0">
                      :
                    </h2>
                    <Popover>
                      <div className="relative">
                        <Input
                          type="datetime-local"
                          className="cursor-pointer"
                          placeholder="Bis"
                          value={
                            toDateThermal
                              ? format(toDateThermal, "yyyy-MM-dd'T'HH:mm")
                              : ""
                          }
                          //empty field befor input for reload
                          onFocus={() => setToDateThermal(undefined)}
                          onChange={(e) => {
                            const value = e.target.value;
                            setToDateThermal(
                              value ? new Date(value) : undefined
                            );
                          }}
                        />
                      </div>
                    </Popover>
                    <div>
                      <div className="flex items-center h-9 ml-5 space-x-2 rounded-lg border bg-white px-3 dark:bg-transparent">
                        <button
                          onClick={thermalLast30Min}
                          className="text-sm text-gray-700 hover:underline focus:outline-none dark:text-white"
                        >
                          last 30 Minutes
                        </button>
                        <div className="h-6 border-l border-gray-300 mx-2" />
                        <button
                          onClick={thermalLastHour}
                          className="text-sm text-gray-700 hover:underline focus:outline-none dark:text-white"
                        >
                          last Hour
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                  onClick={() => minimizeCards("CpuThermalCard")}
                  className={`size-6 mr-5 cursor-pointer transition-transform" ${
                    collapsedCard.CpuThermalCard ? "rotate-180" : ""
                  }`}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </div>

              {!collapsedCard.CpuThermalCard && (
                <ResponsiveContainer width="90%" height="90%">
                  <LineChart
                    width={500}
                    height={300}
                    data={filteredDataCpuThermal.slice().reverse()}
                    margin={{
                      top: 5,
                      right: 30,
                      left: 20,
                      bottom: 5,
                    }}
                  >
                    <CartesianGrid strokeDasharray="5 5" />
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={formatDateMultiline}
                    />
                    <YAxis
                      dataKey="value"
                      domain={[30, 80]}
                      ticks={[40, 50, 60, 70, 80]}
                    />
                    <Tooltip />
                    <Legend />
                    {redZonesCpuThermal.map((zone, index) => (
                      <ReferenceArea
                        key={index}
                        x1={zone.start}
                        x2={zone.end}
                        strokeOpacity={0}
                        fill="red"
                        fillOpacity={0.1}
                      />
                    ))}
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="#8884d8"
                      activeDot={false}
                      dot={({ cx, cy, payload }) => {
                        const border = payload.value >= 43;
                        return (
                          <circle
                            key={`dot-${payload.timestamp}`}
                            cx={cx}
                            cy={cy}
                            //if value is above the border dots geting 0 radius so they are invisible else they are red
                            r={border ? 2 : 0}
                            fill={border ? "red" : "transparent"}
                            stroke="none"
                          />
                        );
                      }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Card>
          </CardContent>
        </Card>
      </div>
    </>
  );
};
export default Details;
