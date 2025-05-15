import { Card, CardContent, CardTitle } from "@/components/ui/card";
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

const Details: React.FC = () => {
  const redZones = useRedZones(data, 80);
  const [collapsedCard, setCollapsedCard] = useState<Record<string, boolean>>({
    smallCard1: false,
    smallCard2: false,
    smallCard3: false,
    CPUUsageCard: false,
    RAMUsageCard: false,
  });
  const [, setSearchError] = useState(false);

  // Hardcoded for now; replace with useParams() when routing
  const charger_id = "d2d67b85-f56b-4a50-842d-92f210e77076";

  const [controllerCpuUsage, setControllerCpuUsage] = useState<string>();
  const [
    controllertemperaturecpu_thermal,
    setControllertemperaturecpu_thermal,
  ] = useState<string>();
  const [controllerCpuUsageData, setControllerCpuUsageData] = useState<
    unknown[]
  >([]);
  const [
    controllertemperaturecpu_thermalData,
    setControllertemperaturecpu_thermalData,
  ] = useState<unknown[]>([]);
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
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/${controllerCpuUsage}?limit=50`
        );
        setControllerCpuUsageData(respUsage.data);
        console.log("CPU Usage:", respUsage.data);

        // CPU Thermal
        const respThermal = await axios.get(
          `http://127.0.0.1:8000/v1/telemetry/${charger_id}/${controllertemperaturecpu_thermal}?limit=50`
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
    return `${day}.${month}`;
  };

  return (
    <div className="flex justify-center items-center mt-5">
      <Card className=" bg-white shadow-md w-11/12 min-h-11/12">
        <CardTitle className="ml-5">Charger 1</CardTitle>
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
          <div className="flex justify-around min-h-1/2 mt-20">
            <Card
              className={`mr-6 w-6/12 transition-all duration-300 ${
                collapsedCard.CPUUsageCard ? "h-16" : "h-96"
              }`}
            >
              <div className="flex justify-between">
                <CardTitle className="ml-5">
                  CPU Usage of Charger {charger_id}
                </CardTitle>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                  onClick={() => minimizeCards("CPUUsageCard")}
                  className={`size-6 mr-5 cursor-pointer transition-transform" ${
                    collapsedCard.CPUUsageCard ? "rotate-180" : ""
                  }`}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </div>
              <ResponsiveContainer width="90%" height="90%">
                <LineChart
                  width={500}
                  height={300}
                  data={controllerCpuUsageData}
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
            </Card>
            <Card
              className={` w-6/12 transition-all duration-300 ${
                collapsedCard.RAMUsageCard ? "h-16" : "h-96"
              }`}
            >
              <div className="flex justify-between">
                <CardTitle className="ml-5">
                  CPU Thermal of Charger {charger_id}
                </CardTitle>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                  onClick={() => minimizeCards("RAMUsageCard")}
                  className={`size-6 mr-5 cursor-pointer transition-transform" ${
                    collapsedCard.RAMUsage ? "rotate-180" : ""
                  }`}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </div>
              <ResponsiveContainer width="90%" height="90%">
                <LineChart
                  width={500}
                  height={300}
                  data={controllertemperaturecpu_thermalData}
                  margin={{
                    top: 5,
                    right: 30,
                    left: 20,
                    bottom: 5,
                  }}
                >
                  <CartesianGrid strokeDasharray="5 5" />
                  <XAxis dataKey="timestamp" />
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
            </Card>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
export default Details;
