# 📘 Tecnical Documentation

## 📁 `FileName.ts(x)`

### a. `functionName(param: Type): returntype`

**Description:**  
_short description of the function_

**Code:**

```ts
// insert code here
```

## 📁 `Landingpage.tsx`

### a. `getAllChargers(): JSON Array`

**Description:**  
Function sends GET request API call to get all available chargers with their base information: (_"charger_name", "last_seen", "online", "manufacturer_name", "charger_id", "firmware_version", "state" and "created"_).

**Code:**

```ts
const resp = await axios.get<Charger[]>(
      "http://127.0.0.1:8000/v1/chargers/available"
    );
    return resp.data;
```

### b. `getCombinedChargerData(charger_id): Object`

**Description:**  
Function sends GET requests API calls to get the specified telemetry data (here: CPU Usage and CPU Temperature). It combines the telemetry data with the base charger data and returns it as an object.

**Code:**

```ts
const [value1Res, value2Res] = await Promise.all([
    axios.get<TelemetryData[]>(
        `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllerCpuUsage`),

    axios.get<TelemetryData[]>(
        `http://127.0.0.1:8000/v1/telemetry/${charger.charger_id}/controllertemperaturecpu-thermal`),
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
## 📁 `Favorites.tsx`

### a. `getFavorites(user_id): JSON Array`

**Description:**  
Function sends GET request API call to retrieve all favoured charger ids of the current user (based on the transferred user id).

**Code:**

```ts
const resp = await axios.get<string[]>(
        `http://127.0.0.1:8000/v1/favorites?user_id=${userId}`
      );
      return resp.data;
```

### b. `toggleFavorites(charger_id, user_id): `

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
},[]

```