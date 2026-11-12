import {
  Activity, Antenna, Battery, Beaker, Bluetooth, Bookmark, Bot, Box, Building2,
  Cable, Camera, CircuitBoard, Clock3, Cloud, Cylinder, Database, DoorClosed,
  Droplet, EthernetPort, Factory, Fan, Flag, Flame, Folder, FolderTree, Gauge, Globe,
  House, Layers, LayoutGrid, Lightbulb, Link2, List, Magnet, Map as MapIcon, MapPin, Navigation,
  Network, Plug, Radio, RotateCw, Router, Ruler, SatelliteDish, Server, Settings, Sun, Tag,
  Thermometer, ToggleLeft, Usb, Volume2, Warehouse, Waypoints, Weight, Wifi, Wind,
  Wrench, Zap,
  type LucideIcon,
} from "lucide-react";
import type { SystemEntityKind } from "@/types/system";
import { Device, Motor, Oscillation, Pump, Valve } from "./symbols";

type IconDefinition = { id: string; label: string; keywords: string; icon: LucideIcon };
// Keep the four families at 16 icons each. IDs are saved in catalogue documents.
export const SOURCE_ICON_GROUPS: { label: string; icons: IconDefinition[] }[] = [
  { label: "Connectivity", icons: [
    { id: "server", label: "Broker", keywords: "server mqtt rack", icon: Server },
    { id: "router", label: "Gateway", keywords: "router edge network", icon: Router },
    { id: "network", label: "Network", keywords: "nodes topic topology", icon: Network },
    { id: "antenna", label: "Antenna", keywords: "radio wireless transmitter", icon: Antenna },
    { id: "wifi", label: "Wireless", keywords: "wifi connection", icon: Wifi },
    { id: "cloud", label: "Cloud", keywords: "remote internet", icon: Cloud },
    { id: "cable", label: "Cable", keywords: "wired connector ethernet", icon: Cable },
    { id: "plug", label: "Connection", keywords: "plug socket power wired", icon: Plug },
    { id: "link", label: "Link", keywords: "chain bind connect association", icon: Link2 },
    { id: "bluetooth", label: "Bluetooth", keywords: "ble short range wireless", icon: Bluetooth },
    { id: "usb", label: "USB", keywords: "serial bus peripheral interface", icon: Usb },
    { id: "ethernet", label: "Ethernet", keywords: "lan port socket wired rj45", icon: EthernetPort },
    { id: "internet", label: "Internet", keywords: "globe wan world remote", icon: Globe },
    { id: "database", label: "Database", keywords: "storage historian archive data", icon: Database },
    { id: "satellite", label: "Satellite", keywords: "dish uplink remote receiver", icon: SatelliteDish },
    { id: "hub", label: "Hub", keywords: "nodes junction distribution mesh", icon: Waypoints },
  ] },
  { label: "Equipment", icons: [
    { id: "cpu", label: "Device", keywords: "chip controller plc entity", icon: Device },
    { id: "sensor", label: "Sensor", keywords: "probe reading radio iot", icon: Radio },
    { id: "circuit", label: "Circuit", keywords: "board electronics pcb", icon: CircuitBoard },
    { id: "motor", label: "Motor", keywords: "machine engine drive rpm", icon: Motor },
    { id: "pump", label: "Pump", keywords: "water fluid flow hydraulic", icon: Pump },
    { id: "valve", label: "Valve", keywords: "pipe process flow pressure", icon: Valve },
    { id: "fan", label: "Fan", keywords: "ventilation cooling hvac", icon: Fan },
    { id: "battery", label: "Battery", keywords: "storage charge energy", icon: Battery },
    { id: "gear", label: "Gear", keywords: "cog machinery mechanical gearbox", icon: Settings },
    { id: "robot", label: "Robot", keywords: "bot automation robotics", icon: Bot },
    { id: "tool", label: "Tool", keywords: "wrench maintenance service repair", icon: Wrench },
    { id: "lamp", label: "Lamp", keywords: "bulb lighting indicator", icon: Lightbulb },
    { id: "switch", label: "Switch", keywords: "toggle relay on off actuator", icon: ToggleLeft },
    { id: "heater", label: "Heater", keywords: "flame furnace burner boiler heat", icon: Flame },
    { id: "tank", label: "Tank", keywords: "cylinder reservoir vessel silo", icon: Cylinder },
    { id: "camera", label: "Camera", keywords: "vision imaging optical inspection", icon: Camera },
  ] },
  { label: "Measurements", icons: [
    { id: "temperature", label: "Temperature", keywords: "thermometer heat celsius", icon: Thermometer },
    { id: "humidity", label: "Humidity", keywords: "droplet water moisture rain", icon: Droplet },
    { id: "pressure", label: "Pressure", keywords: "gauge meter bar speed", icon: Gauge },
    { id: "power", label: "Power", keywords: "electricity current voltage energy", icon: Zap },
    { id: "wave", label: "Vibration", keywords: "wave frequency oscillation amplitude", icon: Oscillation },
    { id: "wind", label: "Air flow", keywords: "wind ventilation gas", icon: Wind },
    { id: "light", label: "Light", keywords: "sun solar illumination lux", icon: Sun },
    { id: "activity", label: "Signal", keywords: "activity pulse reading telemetry", icon: Activity },
    { id: "sound", label: "Sound", keywords: "speaker volume noise acoustic decibel", icon: Volume2 },
    { id: "time", label: "Time", keywords: "clock duration elapsed period", icon: Clock3 },
    { id: "distance", label: "Distance", keywords: "ruler length displacement proximity", icon: Ruler },
    { id: "weight", label: "Weight", keywords: "mass load scale kilogram", icon: Weight },
    { id: "direction", label: "Direction", keywords: "navigation bearing heading orientation", icon: Navigation },
    { id: "volume", label: "Volume", keywords: "beaker liquid capacity litre level", icon: Beaker },
    { id: "rotation", label: "Rotation", keywords: "angular speed rpm turns revolutions", icon: RotateCw },
    { id: "magnetism", label: "Magnetism", keywords: "magnet magnetic field flux hall", icon: Magnet },
  ] },
  { label: "Organisation", icons: [
    { id: "box", label: "Asset", keywords: "box entity object", icon: Box },
    { id: "folder", label: "Topic", keywords: "folder path directory", icon: Folder },
    { id: "layers", label: "Collection", keywords: "layers group", icon: Layers },
    { id: "tag", label: "Tag", keywords: "label category", icon: Tag },
    { id: "building", label: "Building", keywords: "site floor office", icon: Building2 },
    { id: "house", label: "Room", keywords: "house home space door", icon: DoorClosed },
    { id: "location", label: "Location", keywords: "map pin position gps", icon: MapPin },
    { id: "factory", label: "Factory", keywords: "industrial plant production site", icon: Factory },
    { id: "warehouse", label: "Warehouse", keywords: "storage depot inventory stock", icon: Warehouse },
    { id: "home", label: "Home", keywords: "house residential smart home", icon: House },
    { id: "area", label: "Area", keywords: "grid layout section floor", icon: LayoutGrid },
    { id: "zone", label: "Zone", keywords: "map region territory boundary", icon: MapIcon },
    { id: "hierarchy", label: "Hierarchy", keywords: "tree parent child structure", icon: FolderTree },
    { id: "list", label: "List", keywords: "rows items sequence inventory", icon: List },
    { id: "site", label: "Site", keywords: "flag facility landmark location", icon: Flag },
    { id: "reference", label: "Reference", keywords: "bookmark saved marker baseline", icon: Bookmark },
  ] },
];

export type SourceIconKind = SystemEntityKind | "root" | "topic" | "reading" | "unassigned" | "collection";
const defaults: Record<SourceIconKind, string> = {
  connection: "server", device: "cpu", stream: "sensor", reading: "sensor",
  topic: "folder", group: "layers", collection: "layers", root: "network", unassigned: "folder",
};
const icons = new Map(SOURCE_ICON_GROUPS.flatMap(group => group.icons.map(icon => [icon.id, icon] as const)));
export const sourceIcon = (kind: SourceIconKind, id?: string) => icons.get(id ?? "") ?? icons.get(defaults[kind])!;
