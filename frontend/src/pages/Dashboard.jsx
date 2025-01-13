import React, { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"; // shadcn components

const Dashboard = () => {
  const [data, setData] = useState([]);

  useEffect(() => {
    fetch("http://localhost:8000/data")
      .then((response) => response.json())
      .then((result) => setData(result.data))
      .catch((error) => console.error("Error fetching data:", error));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Time-Series Dashboard</CardTitle>
      </CardHeader>
      <CardContent>
        <LineChart width={800} height={400} data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="value" stroke="#8884d8" />
        </LineChart>
      </CardContent>
    </Card>
  );
};

export default Dashboard;