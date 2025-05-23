import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import mockdata from "../mockData/MockDataDetails.json";
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
// import { useParams } from "react-router-dom";
import axios from "axios";
import { format } from "date-fns";
import { Popover } from "@/components/ui/popover";

// import {
//   Table,
//   TableBody,
//   TableCaption,
//   TableCell,
//   TableHead,
//   TableHeader,
//   TableRow,
// } from "@/components/ui/table";

const data = mockdata;

//Mockdate for the short Infos cards
// const pieData = [
//   { name: "online", value: 75 },
//   { name: "offline", value: 25 },
// ];
// const barData = [
//   { Day: "Monday", UsageCount: 25 },
//   { Day: "Tuesday", UsageCount: 100 },
//   { Day: "Wednesday", UsageCount: 10 },
//   { Day: "Thursday", UsageCount: 50 },
//   { Day: "Friday", UsageCount: 72 },
//   { Day: "Saturday", UsageCount: 122 },
// ];

interface Cpu {
  timestamp: string;
  value: number;
}

const Details: React.FC = () => {
  const redZones = useRedZones(data, 80);
  const [collapsedCard, setCollapsedCard] = useState<Record<string, boolean>>({
    smallCard1: false,
    smallCard2: false,
    smallCard3: false,
    CpuUsageCard: false,
    CpuThermalCard: false,
  });
  const [, setSearchError] = useState(false);
  // Hardcoded for now; replace with useParams() when routing
  const charger_id = "d2d67b85-f56b-4a50-842d-92f210e77076";

  const [controllerCpuUsage, setControllerCpuUsage] = useState<string>();
  const [
    controllertemperaturecpu_thermal,
    setControllertemperaturecpu_thermal,
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
        // Search in results for this 2 keys
        const cpuUsageKey = results.find(
          (t) => t.toLowerCase() === "controllercpuusage"
        );
        const cpuThermalKey = results.find(
          (t) => t.toLowerCase() === "controllertemperaturecpu-thermal"
        );

        if (cpuUsageKey && cpuThermalKey) {
          setControllerCpuUsage(cpuUsageKey);
          setControllertemperaturecpu_thermal(cpuThermalKey);
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
  //    - first fetch
  //    - then every 20 seconds repeat
  useEffect(() => {
    if (
      !charger_id ||
      !controllerCpuUsage ||
      !controllertemperaturecpu_thermal
    ) {
      return;
    }

    async function fetchTelemetryData() {
      try {
        // CPU Usage
        const respUsage = await axios.get(
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/${controllerCpuUsage}?limit=100`
        );
        setControllerCpuUsageData(respUsage.data);
        console.log("CPU Usage:", respUsage.data);

        // CPU Thermal
        const respThermal = await axios.get(
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/${controllertemperaturecpu_thermal}?limit=100`
        );
        setControllertemperaturecpu_thermalData(respThermal.data);
        console.log("CPU Thermal:", respThermal.data);
      } catch (error) {
        console.error("Fehler beim Daten-Fetch:", error);
        setSearchError(true);
      }
    }

    // initial
    fetchTelemetryData();

    intervalRef.current = setInterval(fetchTelemetryData, 20000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [charger_id, controllerCpuUsage, controllertemperaturecpu_thermal]);

  const minimizeCards = (key: string) => {
    setCollapsedCard((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

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
  const filteredDataCpuUsage = controllerCpuUsageData.filter((d) => {
    const t = new Date(d.timestamp).getTime();
    const f = fromDateUsage?.getTime() ?? -Infinity;
    const u = toDateUsage?.getTime() ?? Infinity;
    return t >= f && t <= u;
  });

  const filteredDataCpuThermal = controllertemperaturecpu_thermalData.filter(
    (d) => {
      const t = new Date(d.timestamp).getTime();
      const f = fromDateThermal?.getTime() ?? -Infinity;
      const u = toDateThermal?.getTime() ?? Infinity;
      return t >= f && t <= u;
    }
  );

  return (
    <div className="flex mt-5">
      <Card className="ml-16 bg-white shadow-md w-11/12 min-h-11/12">
        <CardTitle className="ml-5">Charger {charger_id}</CardTitle>
        <CardContent>
          <div className="flex justify-between">
            {/* <Card
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
                        type="Date"
                        className="cursor-pointer"
                        placeholder="Von"
                        value={
                          fromDateUsage
                            ? format(fromDateUsage, "yyyy-MM-dd")
                            : ""
                        }
                        onChange={(e) => {
                          const value = e.target.value;
                          setFromDateUsage(value ? new Date(value) : undefined);
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
                        type="Date"
                        className="cursor-pointer"
                        placeholder="Bis"
                        value={
                          toDateUsage ? format(toDateUsage, "yyyy-MM-dd") : ""
                        }
                        onChange={(e) => {
                          const value = e.target.value;
                          setToDateUsage(value ? new Date(value) : undefined);
                        }}
                      />
                    </div>
                  </Popover>
                  <div>
                    <div className="flex items-center h-9 ml-5 space-x-2 rounded-lg border bg-white px-3">
                      <button
                        // onClick={onLast8h}
                        className="text-sm text-gray-700 hover:underline focus:outline-none"
                      >
                        Letzte 8 h
                      </button>
                      <div className="h-6 border-l border-gray-300 mx-2" />
                      <button
                        // onClick={onLast24h}
                        className="text-sm text-gray-700 hover:underline focus:outline-none"
                      >
                        Letzte 24 h
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
                  {redZones.map((zone, index) => (
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
                    activeDot={{ r: 8 }}
                    dot={({ cx, cy, payload }) => {
                      const color = payload.value >= 80 ? "red" : "#8884d8";
                      return (
                        <circle
                          key={`dot-${payload.timestamp}`}
                          cx={cx}
                          cy={cy}
                          r={4}
                          fill={color}
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
                        type="Date"
                        className="cursor-pointer"
                        placeholder="Von"
                        value={
                          fromDateThermal
                            ? format(fromDateThermal, "yyyy-MM-dd")
                            : ""
                        }
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
                        type="Date"
                        className="cursor-pointer"
                        placeholder="Bis"
                        value={
                          toDateThermal
                            ? format(toDateThermal, "yyyy-MM-dd")
                            : ""
                        }
                        onChange={(e) => {
                          const value = e.target.value;
                          setToDateThermal(value ? new Date(value) : undefined);
                        }}
                      />
                    </div>
                  </Popover>
                  <div>
                    <div className="flex items-center h-9 ml-5 space-x-2 rounded-lg border bg-white px-3">
                      <button
                        // onClick={onLast8h}
                        className="text-sm text-gray-700 hover:underline focus:outline-none"
                      >
                        Letzte 8 h
                      </button>
                      <div className="h-6 border-l border-gray-300 mx-2" />
                      <button
                        // onClick={onLast24h}
                        className="text-sm text-gray-700 hover:underline focus:outline-none"
                      >
                        Letzte 24 h
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
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="#8884d8"
                    activeDot={{ r: 8 }}
                    dot={({ cx, cy, payload }) => {
                      //wenn value >= 59 dann roter punkt z.b.
                      const color = payload.value >= 59 ? "red" : "#8884d8";
                      return (
                        <circle
                          key={`dot-${payload.timestamp}`}
                          cx={cx}
                          cy={cy}
                          r={4}
                          fill={color}
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
  );
};
export default Details;
