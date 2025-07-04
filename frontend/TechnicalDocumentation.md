# 📘 Technical Documentation

# 📑 Inhaltsverzeichnis

- [1. Details.tsx](#1-detailstsx)

  - [1.1. formatDateMultiline](#11-formatdatemultilinevalue-string)
  - [1.2. filteredDataCpuUsage](#12-filtereddatacpuusagecpu-cpu)
  - [1.3. handleLastMinutes](#13-handlelastminutesdataarraycpu-setfrom-dateundefined-setto-dateundefined-minutes-number-)

- [2. useRedZones.ts](#2-useredzonests)

  - [2.1. useRedZones](#21-useredzonesstart-string-end-string-)

- [3. Landingpage.tsx](#3-landingpagetsx)

  - [3.1. getAllChargers](#31-getallchargers-json-array)
  - [3.2. getCombinedChargerData](#b-getcombinedchargerdatacharger_id-string-object)

- [4. Favorites.tsx](#4-favoritestsx)

  - [4.1. getFavorites](#41-getfavoritesuser_id-number-json-array)
  - [4.2. toggleFavorites](#42-togglefavoritescharger_id-string-user_id-number-)

- [5. Anomalies.tsx](#5-anomaliestsx)

  - [5.1. getAnomalies](#51-getanomaliescharger_id-string-json-array)
  - [5.2. addAnomaly](#52-addanomalychargerid-string-timestamp-date-telemetry_type-string-anomaly_type-string-anomaly_value-number)
  - [5.3. deleteAnomaly](#53-deleteanomalychargerid-string-timestamp-date-telemetry_type-string-returntype)

- [6. Login.tsx](#6-logintsx)

  - [6.1. handleLogin](#61-handlelogine-reactformevent-promisevoid)

- [7. Registration.tsx](#7-registrationtsx)

  - [7.1. handleRegister](#71-handleregistere-reactformevent-promisevoid)

- [8. Verification.tsx](#8-verificationtsx)

  - [8.1. Verification](#81-verification-reactfc)

- [9. ForgotPassword.tsx](#9-forgotpasswordtsx)

  - [9.1. handleSubmit](#91-handlesubmite-reactformevent)

- [10. AuthContext.tsx](#10-authcontexttsx)

  - [10.1. useEffect](#101-useeffect--)
  - [10.2. login](#102-loginnewtoken-string-void)
  - [10.3. logout](#103-logout-void)
  - [10.4. isAuthenticated](#104-isauthenticated-boolean)
  - [10.5. useAuth](#105-useauth-authcontexttype)
  - [10.6. AuthProvider](#106-authproviderchildrenchildren)

- [11. ProtectedRoute.tsx](#11-protectedroutetsx)

  - [11.1. ProtectedRoute](#111-protectedroute-children--children-jsxelement-jsxelement)

- [12. FetchContext.tsx](#12-fetchcontexttsx)
  - [12.1. getTelemetryTypes](#121-gettelemetrytypeschargerid-string-promisestring)
  - [12.2. getTelemetryData](#122-gettelemetrydatachargerid-string-telemetrykey-string-promisecpu)
  - [12.3. getAllChargers](#123-getallchargers-promisecharger)
  - [12.4. getFavorites](#124-getfavoritesuserid-number-promisestring)
  - [12.5. toggleFavorite](#125-togglefavoritechargerid-string-userid-number-iscurrentlyfavorite-boolean-promisevoid)
  - [12.6. getCombinedChargerData](#126-getcombinedchargerdatachargers-charger-promisecombineddata)
  - [12.7. getAnomalies](#127-getanomalieschargerid-string-promiseanomaly)
  - [12.8. addAnomaly](#128-addanomalychargerid-string-timestamp-date-telemetry_type-string-promisevoid)
  - [12.9. deleteAnomaly](#129-deleteanomalychargerid-string-timestamp-date-telemetry_type-string-promisevoid)
  - [12.10. syncChargers](#1210-syncchargers-promisevoid)
  - [12.11. syncTelemetry](#1211-synctelemetry-promisevoid)
  - [12.12. syncTelemetryShort](#1212-synctelemetryshort-promisevoid)
  - [12.13. loadCpuUsage](#1213-loadcpuusagechargerid-string-promisevoid)
  - [12.14. loadCpuThermal](#1214-loadcputhermalchargerid-string-promisevoid)
  - [12.15. loadMonitoring](#1215-loadmonitoringchargerid-string-promisevoid)

##

## 1. 📁 `Details.tsx`

### 1.1. `formatDateMultiline(value: string)`

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

### 1.2. `filteredDataCpuUsage(CPU: cpu)`

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

### 1.3. `handleLastMinutes(dataArray:CPU[], setFrom: Date|undefined, setTo: Date|undefined, minutes: number): `

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

## 2. 📁 `useRedZones.ts`

### 2.1. `useRedZones(start: string, end: string): `

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

## 3. 📁 `Landingpage.tsx`

### 3.1. `getAllChargers(): JSON Array`

**Description:**  
Function sends GET request API call to get all available chargers with their base information: (_"charger_name", "last_seen", "online", "manufacturer_name", "charger_id", "firmware_version", "state" and "created"_).

**Code:**

```ts
const resp = await axios.get<Charger[]>(
  "http://127.0.0.1:8000/v1/chargers/available"
);
return resp.data;
```

### b. `getCombinedChargerData(charger_id: string): Object`

**Description:**  
Function sends GET requests API calls to get the specified telemetry data (here: CPU Usage and CPU Temperature). It combines the telemetry data with the base charger data and returns it as an object.

**Code:**

```ts
const [value1Res, value2Res] = await Promise.all([
  axios.get<TelemetryData[]>(
    `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllerCpuUsage`
  ),

  axios.get<TelemetryData[]>(
    `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllertemperaturecpu-thermal`
  ),
]);
return {
  charger_id: charger.charger_id,
  charger_name: charger.charger_name,
  online: charger.online,
  state: charger.state,
  last_seen: charger.last_seen,
  value1: value1Res.data[0]?.value ?? null,
  value2: value2Res.data[0]?.value ?? null,
};
```

## 4. 📁 `Favorites.tsx`

### 4.1. `getFavorites(user_id: number): JSON Array`

**Description:**  
Function sends GET request API call to retrieve all favoured charger ids of the current user (based on the transferred user id).

**Code:**

```ts
const resp = await axios.get<string[]>(
  `http://127.0.0.1:8000/v1/favorites?user_id=${userId}`
);
return resp.data;
```

### 4.2. `toggleFavorites(charger_id: string, user_id: number): `

**Description:**  
Function that is called when a user clicks on the favorite/star icon. The favourites entry for the selected charger is deleted if it was already a favourite. Otherwise, a favourites entry is created.

**Code:**

```ts
async (chargerId: string, userId: number, isCurrentlyFavorite: boolean) => {
  if (isCurrentlyFavorite) {
    await axios.delete("http://127.0.0.1:8000/v1/favorites", {
      data: { charger_id: chargerId, user_id: userId },
    });
  } else {
    await axios.post("http://127.0.0.1:8000/v1/favorites", {
      charger_id: chargerId,
      user_id: userId,
    });
  }
},
  [];
```

## 5. 📁 `Anomalies.tsx`

### 5.1. `getAnomalies(charger_id: string): JSON Array`

**Description:**  
Function sends GET requests API calls to get all the anomaly data from a specific charger. It returns the "charger_id", "timestamp", "telemetry_type", "anomaly_type" and "anomaly_value".

**Code:**

```ts
async (chargerId: string): Promise<Anomaly[]> => {
  const resp = await axios.get<Anomaly[]>(
    `http://127.0.0.1:8000/v1/anomalies?charger_id=${chargerId}`
  );
  return resp.data;
};
```

### 5.2. `addAnomaly(chargerId: string, timestamp: Date, telemetry_type: string, anomaly_type: string, anomaly_value: number):`

**Description:**  
Function needs to be called with a charger_id, timestamp, telemtry_type, anomaly_type and an anomaly_value to add an anomaly to the database.

**Code:**

```ts
async (
  chargerId: string,
  timestamp: Date,
  telemetry_type: string,
  anomaly_type: string,
  anomaly_value: number
) => {
  await axios.post("http://127.0.0.1:8000/v1/anomalies", {
    charger_id: chargerId,
    timestamp: timestamp,
    telemetry_type: telemetry_type,
    anomaly_type: anomaly_type,
    anomaly_value: anomaly_value,
  });
};
```

### 5.3. `deleteAnomaly(chargerId: string, timestamp: Date, telemetry_type: string): returntype`

**Description:**  
Function deletes a given anomaly entry based on the specified charger_id, timestamp and telemetry_type combination.

**Code:**

```ts
async (chargerId: string, timestamp: Date, telemetry_type: string) => {
  const params = new URLSearchParams({
    charger_id: chargerId,
    timestamp: timestamp.toISOString(), // in ISO-Format
    telemetry_type: telemetry_type,
      });

  await axios.delete(
    `http://127.0.0.1:8000/v1/anomalies?${params.toString()}`
  );
},
```

## 6. 📁 `Login.tsx`

### 6.1. `handleLogin(e: React.FormEvent): Promise<void>`

**Description:**  
Handles the login form submission. Sends a `POST` request to the backend with email and password. Based on `rememberMe`, it stores the token in `localStorage` or `sessionStorage`, logs the user in via context, triggers charger and telemetry data sync, and navigates to the home page after a delay.

**Code:**

```ts
const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  try {
    const response = await fetch("http://localhost:8000/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      setMessage(errorData.detail || "Login failed");
      return;
    }

    const data: LoginResponse = await response.json();

    if (rememberMe) {
      localStorage.setItem("token", data.access_token);
    } else {
      sessionStorage.setItem("token", data.access_token);
    }

    login(data.access_token);
    syncChargers();
    syncTelemetry();

    setTimeout(() => {
      navigate("/");
    }, 2000);
  } catch (error) {
    console.error(error);
    setMessage("An error occurred");
  }
};
```

---

## 7. 📁 `Registration.tsx`

### 7.1. `handleRegister(e: React.FormEvent): Promise<void>`

**Description:**
Handles the registration form submission. Performs validation (password match, minimum length), sends a POST request to register the user, displays success or error messages, and redirects to the login page after successful registration.

**Code:**

```ts
const handleRegister = async (e: React.FormEvent) => {
  e.preventDefault();
  setIsError(false);

  if (password !== confirmPassword) {
    setMessage("Passwords do not match.");
    setIsError(true);
    return;
  }

  if (password.length < 8) {
    setMessage("Password should be at least 8 characters long.");
    setIsError(true);
    return;
  }

  try {
    const response = await fetch("http://localhost:8000/v1/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password, role: "user" }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      setMessage(errorData.detail || "Registration failed");
      setIsError(true);
      return;
    }

    const data: RegistrationResponse = await response.json();
    setMessage(
      data.message || "Registration successful! Please check your email."
    );
    setIsError(false);

    setTimeout(() => {
      window.location.href = "/login";
    }, 3000);
  } catch (error) {
    console.error(error);
    setMessage("An error occurred.");
    setIsError(true);
  }
};
```

---

## 8. 📁 `Verification.tsx`

### 8.1. `Verification: React.FC`

**Description:**  
Handles the email verification process. It extracts a token from the URL query parameters and sends a `GET` request to the backend to verify the user’s email address. Based on the API response, it updates the status message shown to the user.

**Code:**

```ts
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import axios from "axios";

const Verification: React.FC = () => {
  const location = useLocation();
  const [status, setStatus] = useState<string>("Verifying...");
  const queryParams = new URLSearchParams(location.search);
  const token = queryParams.get("token");

  useEffect(() => {
    if (token) {
      axios
        .get(`http://localhost:8000/v1/auth/verify-email?token=${token}`)
        .then((_response) => {
          setStatus("Email verified successfully!");
        })
        .catch((_error) => {
          setStatus("Verification failed. Please try again.");
        });
    } else {
      setStatus("Invalid verification link.");
    }
  }, [token]);

  return (
    <div>
      <h1>{status}</h1>
    </div>
  );
};

export default Verification;
```

---

## 9. 📁 `ForgotPassword.tsx`

### 9.1. `handleSubmit(e: React.FormEvent)`

**Description:**

This function is triggered when the forgot password form is submitted. It prevents the default form behavior and sends a POST request to the backend endpoint /v1/auth/forgot-password with the entered email address as JSON. If the request is successful, it displays the response message to the user. If an error occurs (e.g., network issue or backend failure), a generic error message is shown instead.

**Code:**

```tsx
const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();
  try {
    const res = await fetch("http://localhost:8000/v1/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();
    setMessage(data.message);
  } catch (error) {
    setMessage("An error occurred while sending the request.");
  }
};
```

## 10. 📁 `AuthContext.tsx`

### 10.1. `useEffect(() => { ... }, [])`

**Description:**  
On component mount, this effect checks both `localStorage` and `sessionStorage` for a previously saved token. If found, it updates the `token` state and stops the loading state.

**Code:**

```ts
useEffect(() => {
  const savedToken =
    localStorage.getItem("token") || sessionStorage.getItem("token");
  if (savedToken) {
    setToken(savedToken);
  }
  setIsLoading(false);
}, []);
```

---

### 10.2. `login(newToken: string): void`

**Description:**  
Stores a new authentication token into `sessionStorage` and updates the React state to authenticate the user.

**Code:**

```ts
const login = (newToken: string) => {
  sessionStorage.setItem("token", newToken);
  setToken(newToken);
};
```

---

### 10.3. `logout(): void`

**Description:**  
Removes the authentication token from both `sessionStorage` and `localStorage` to log the user out of the session.

**Code:**

```ts
const logout = () => {
  sessionStorage.removeItem("token");
  localStorage.removeItem("token");
};
```

---

### 10.4. `isAuthenticated: boolean`

**Description:**  
Boolean value that indicates if the user is currently authenticated, based on the presence of a valid token.

**Code:**

```ts
const isAuthenticated = !!token;
```

---

### 10.5. `useAuth(): AuthContextType`

**Description:**  
Custom React hook that allows components to access the authentication context. Will throw an error if used outside of the `AuthProvider`.

**Code:**

```ts
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
```

---

### 10.6. `<AuthProvider>{children}</AuthProvider>`

**Description:**  
Component that provides authentication context (token, login/logout, state) to its children.

**Code:**

```ts
<AuthContext.Provider
  value={{ isAuthenticated, token, isLoading, login, logout }}
>
  {children}
</AuthContext.Provider>
```

---

## 11. 📁 `ProtectedRoute.tsx`

### 11.1. `ProtectedRoute({ children }: { children: JSX.Element }): JSX.Element`

**Description:**  
This component serves as a route guard. It ensures that only authenticated users can access certain routes. If authentication is still loading, it shows a loading message. If the user is not authenticated, it redirects to the login page. If authenticated, it renders the protected component (`children`).

**Code:**

```ts
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { JSX } from "react";

export const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="text-center mt-10 text-gray-600">
        Authentication is loading...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};
```

---

## 12. 📁 `FetchContext.tsx`

### 12.1. `getTelemetryTypes(chargerId: string): Promise<string[]>`

**Description:**  
Fetches all available telemetry types (keys) for a given charger by its ID.

**Code:**

```ts
const getTelemetryTypes = useCallback(
  async (chargerId: string): Promise<string[]> => {
    const resp = await axios.get<string[]>(
      `http://127.0.0.1:8000/v1/telemetry/${chargerId}/type`
    );
    return resp.data;
  },
  []
);
```

---

### 12.2. `getTelemetryData(chargerId: string, telemetryKey: string): Promise<Cpu[]>`

**Description:**  
Retrieves telemetry data for a specific charger and telemetry key (e.g., CPU usage or temperature).

**Code:**

```ts
const getTelemetryData = useCallback(
  async (chargerId: string, telemetryKey: string): Promise<Cpu[]> => {
    const resp = await axios.get<Cpu[]>(
      `http://127.0.0.1:8000/v1/telemetry/${chargerId}/${telemetryKey}?limit=1000`
    );
    return resp.data;
  },
  []
);
```

---

### 12.3. `getAllChargers(): Promise<Charger[]>`

**Description:**  
Fetches the list of all currently available chargers.

**Code:**

```ts
const getAllChargers = useCallback(async (): Promise<Charger[]> => {
  const resp = await axios.get<Charger[]>(
    "http://127.0.0.1:8000/v1/chargers/available"
  );
  return resp.data;
}, []);
```

---

### 12.4. `getFavorites(userId: number): Promise<string[]>`

**Description:**  
Returns a list of charger IDs that are marked as favorites for the given user.

**Code:**

```ts
const getFavorites = useCallback(async (userId: number): Promise<string[]> => {
  const resp = await axios.get<string[]>(
    `http://127.0.0.1:8000/v1/favorites?user_id=${userId}`
  );
  return resp.data;
}, []);
```

---

### 12.5. `toggleFavorite(chargerId: string, userId: number, isCurrentlyFavorite: boolean): Promise<void>`

**Description:**  
Adds or removes a charger from the user's favorites, depending on whether it's already marked.

**Code:**

```ts
const toggleFavorite = useCallback(
  async (chargerId: string, userId: number, isCurrentlyFavorite: boolean) => {
    if (isCurrentlyFavorite) {
      await axios.delete("http://127.0.0.1:8000/v1/favorites", {
        data: { charger_id: chargerId, user_id: userId },
      });
    } else {
      await axios.post("http://127.0.0.1:8000/v1/favorites", {
        charger_id: chargerId,
        user_id: userId,
      });
    }
  },
  []
);
```

---

### 12.6. `getCombinedChargerData(chargers: Charger[]): Promise<CombinedData[]>`

**Description:**  
Combines basic charger information with selected telemetry data (CPU usage & temperature) for each charger.

**Code:**

```ts
const getCombinedChargerData = useCallback(
  async (chargers: Charger[]): Promise<CombinedData[]> => {
    const combinedData = await Promise.all(
      chargers.map(async (charger) => {
        try {
          const [value1Res, value2Res] = await Promise.all([
            axios.get<TelemetryData[]>(
              `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllerCpuUsage`
            ),
            axios.get<TelemetryData[]>(
              `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllertemperaturecpu-thermal`
            ),
          ]);
          return {
            charger_id: charger.charger_id,
            charger_name: charger.charger_name,
            online: charger.online,
            state: charger.state,
            last_seen: charger.last_seen,
            value1: value1Res.data[0]?.value ?? null,
            value2: value2Res.data[0]?.value ?? null,
          };
        } catch (error) {
          console.warn(
            `Error at values from Charger ${charger.charger_id}`,
            error
          );
          return {
            charger_id: charger.charger_id,
            charger_name: charger.charger_name,
            online: charger.online,
            state: charger.state,
            last_seen: charger.last_seen,
            value1: null,
            value2: null,
          };
        }
      })
    );
    return combinedData;
  },
  []
);
```

---

### 12.7. `getAnomalies(chargerId: string): Promise<Anomaly[]>`

**Description:**  
Fetches telemetry anomalies associated with the specified charger.

**Code:**

```ts
const getAnomalies = useCallback(
  async (chargerId: string): Promise<Anomaly[]> => {
    const resp = await axios.get<Anomaly[]>(
      `http://127.0.0.1:8000/v1/anomalies?charger_id=${chargerId}`
    );
    return resp.data;
  },
  []
);
```

---

### 12.8. `addAnomaly(chargerId: string, timestamp: Date, telemetry_type: string): Promise<void>`

**Description:**  
Adds an anomaly entry for a specific charger and telemetry type.

**Code:**

```ts
const addAnomaly = useCallback(
  async (chargerId: string, timestamp: Date, telemetry_type: string) => {
    await axios.post("http://127.0.0.1:8000/v1/anomalies", {
      charger_id: chargerId,
      timestamp: timestamp,
      telemetry_type: telemetry_type,
    });
  },
  []
);
```

---

### 12.9. `deleteAnomaly(chargerId: string, timestamp: Date, telemetry_type: string): Promise<void>`

**Description:**  
Deletes an anomaly for a specific charger based on telemetry type and timestamp.

**Code:**

```ts
const deleteAnomaly = useCallback(
  async (chargerId: string, timestamp: Date, telemetry_type: string) => {
    const params = new URLSearchParams({
      charger_id: chargerId,
      timestamp: timestamp.toISOString(), // in ISO-Format
      telemetry_type: telemetry_type,
    });

    await axios.delete(
      `http://127.0.0.1:8000/v1/anomalies?${params.toString()}`
    );
  },
  []
);
```

---

### 12.10. `syncChargers(): Promise<void>`

**Description:**  
Triggers server-side synchronization for charger data.

**Code:**

```ts
const syncChargers = useCallback(async (): Promise<void> => {
  try {
    await axios.post("http://127.0.0.1:8000/v1/chargers/sync", null);
  } catch (err) {
    console.warn("syncChargers failed:", err);
  }
}, []);
```

---

### 12.11. `syncTelemetry(): Promise<void>`

**Description:**  
Triggers full telemetry data sync (up to 10,000 records)

**Code:**

```ts
const syncTelemetry = useCallback(async (): Promise<void> => {
  try {
    await axios.post(
      "http://127.0.0.1:8000/v1/telemetry/sync?limit=10000",
      null
    );
  } catch (err) {
    console.warn("syncTelemetry failed:", err);
  }
}, []);
```

---

### 12.12. `syncTelemetryShort(): Promise<void>`

**Description:**  
Triggers a short sync for recent telemetry data (100 records).

**Code:**

```ts
const syncTelemetryShort = useCallback(async (): Promise<void> => {
  try {
    await axios.post("http://127.0.0.1:8000/v1/telemetry/sync?limit=100", null);
  } catch (err) {
    console.warn("syncTelemetryShort failed:", err);
  }
}, []);
```

---

### 12.13. `loadCpuUsage(chargerId: string): Promise<void>`

**Description:**  
Loads CPU usage telemetry for a charger and saves it in state.

**Code:**

```ts
const loadCpuUsage = useCallback(
  async (chargerId: string) => {
    try {
      // //Sync Telemetry first
      // await syncTelemetryShort();

      // now get the Keys
      const types = await getTelemetryTypes(chargerId);
      const cpuUsageKey = types.find((t) =>
        t.toLowerCase().includes("controllercpuusage")
      );
      if (!cpuUsageKey) {
        console.warn(`Usage-Key for Charger ${chargerId} not found:`, types);
        setSearchError(true);
        return;
      }

      // then get the Data
      const data = await getTelemetryData(chargerId, cpuUsageKey);

      // write the data in the Map
      setCpuUsageMap((prev) => ({
        ...prev,
        [chargerId]: data,
      }));
      setSearchError(false);
    } catch (err) {
      console.error("Error loading CPU Usage:", err);
      setSearchError(true);
    }
  },
  [getTelemetryTypes, getTelemetryData, syncTelemetry]
);
```

---

### 12.14. `loadCpuThermal(chargerId: string): Promise<void>`

**Description:**  
Loads CPU temperature telemetry for a charger and updates context state.

**Code:**

```ts
const loadCpuThermal = useCallback(
  async (chargerId: string) => {
    try {
      // //Sync Telemetry first
      // await syncTelemetryShort();

      // now get the Keys
      const types = await getTelemetryTypes(chargerId);
      const cpuThermalKey = types.find((t) =>
        t.toLowerCase().includes("controllertemperaturecpu-thermal")
      );
      if (!cpuThermalKey) {
        console.warn(`Thermal-Key for Charger ${chargerId} not found:`, types);
        setSearchError(true);
        return;
      }

      // then get the Data
      const data = await getTelemetryData(chargerId, cpuThermalKey);

      // write the data in the Map
      setCpuThermalMap((prev) => ({
        ...prev,
        [chargerId]: data,
      }));
      setSearchError(false);
    } catch (err) {
      console.error("Error loading CPU Thermal:", err);
      setSearchError(true);
    }
  },
  [getTelemetryTypes, getTelemetryData, syncTelemetry]
);
```

---

### 12.15. `loadMonitoring(chargerId: string): Promise<void>`

**Description:**  
Loads monitoring data (e.g., system and controller state) and stores it in context state.

**Code:**

```ts
const loadMonitoring = useCallback(async (chargerId: string) => {
  try {
    //  get the Keys
    const types = await getTelemetryTypes(chargerId);
    // filter for keytypes - here all key types without CPU temp and usage
    const keys = types.filter(
      (t) =>
        t.toLowerCase().startsWith("system") ||
        t.toLowerCase().startsWith("controllerstate")
    );
    if (keys.length === 0) {
      console.warn(
        `Key with key value "system" in Charger ${chargerId} not found`,
        types
      );
      setSearchError(true);
      return;
    }

    //  get the Data
    const entries = await Promise.all(
      keys.map(async (key) => {
        const rawData = await getTelemetryData(chargerId, key);
        const data: Monitoring[] = rawData.map((d) => ({
          type: key,
          value: d.value,
        }));
        return [key, data] as const;
      })
    );

    // write the data in the Map
    setMonitoringMap((prev) => ({
      ...prev,
      ...Object.fromEntries(entries),
    }));
    setSearchError(false);
  } catch (err) {
    console.error("Error loading CPU Usage:", err);
    setSearchError(true);
  }
}, []);
```
