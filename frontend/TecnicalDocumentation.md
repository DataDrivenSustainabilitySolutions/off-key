# 📘 Tecnical Documentation

## 📁 `FileName.ts(x)`

### a. `functionName(param: Type): returntype`

**Description:**  
_short description of the function_

**Code:**

```ts
// insert code here
```

## 📁 `Details.tsx`

### 1. `formatDateMultiline(value: string)`

**Returntype:**
string

**Description:**  
This is a function to format the Timestamps which are given from the
Datapoints for CPU Usage and CPU Thermal for the Linecharts to show
in the X Axis. The function filters the Timestamp and sets it up in the format day:month, hour:minute:second

**Code:**

```ts
const formatDateMultiline = (value: string) => {
  const date = new Date(value);
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${day}.${month}, ${hour}:${minute}:${second}`;
};
```

### 2. `filteredDataCpuUsage(CPU: cpu)`

**Returntype:**
number

**Description:**  
Filters The Timestamp and matches it with the input from the user.
Its the function for the Datepicker from and to date and the time.
The same is done with "const filteredDataCpuThermal".

**Code:**

```ts
const filteredDataCpuUsage = controllerCpuUsageData.filter((cpu) => {
  const t = new Date(cpu.timestamp).getTime();
  const f = fromDateUsage?.getTime() ?? -Infinity;
  const u = toDateUsage?.getTime() ?? Infinity;
  return t >= f && t <= u;
});
```

### 3. `handleLastMinutes(dataArray:CPU[], setFrom: Date|undefined, setTo: Date|undefined, minutes: number): `

**Description:**  
This function takes the data from dataArray and the sets 2 react states "from" and "to". First it calculates the maxTime and o this basis it calculates the minTime. With those 2 it sets a Timespan in which the matching Datapoints will be shown.

**Code:**

```ts
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
// buton function for last 30 minutes and last hour
const usageLast30Min = () =>
  handleLastMinutes(
    controllerCpuUsageData,
    setFromDateUsage,
    setToDateUsage,
    30
  );
const usageLastHour = () =>
  handleLastMinutes(
    controllerCpuUsageData,
    setFromDateUsage,
    setToDateUsage,
    60
  );
const thermalLast30Min = () =>
  handleLastMinutes(
    controllertemperaturecpu_thermalData,
    setFromDateThermal,
    setToDateThermal,
    30
  );
const thermalLastHour = () =>
  handleLastMinutes(
    controllertemperaturecpu_thermalData,
    setFromDateThermal,
    setToDateThermal,
    60
  );
```

**Change Information:**
If you want to change the timepsan (at the moment the 2 button have 30 minutes and 1 hour) you can simply change the 30 or the 60 into whatever you want. Those values have to be set in minutes.

All you have to do to call the function you want is to call it in the Button Component in the Linechart you want.

You can also add more if you want just like "thermalLastHour" for example.

## 📁 `useRedZones.ts`

### a. `useRedZones(start: string, end: string): `

**return:**
zones: start
end

**Description:**  
Is used to mark red Zones in the Linecharts whenever the value is above the treshold.

**Code:**

```ts
export function useRedZones(data: DataPoint[], threshold = 80) {
  return useMemo(() => {
    const zones: { start: string; end: string }[] = [];
    let start: string | null = null;

    for (let i = 0; i < data.length; i++) {
      if (data[i].value >= threshold) {
        if (start === null) start = data[i].timestamp;
      } else {
        if (start !== null) {
          zones.push({ start, end: data[i].timestamp });
          start = null;
        }
      }
    }

    if (start !== null) {
      zones.push({ start, end: data[data.length - 1].timestamp });
    }

    return zones;
  }, [data, threshold]);
}
```
