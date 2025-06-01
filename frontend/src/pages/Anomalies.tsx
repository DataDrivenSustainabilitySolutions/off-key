import { NavigationBar } from "@/components/NavigationBar";

export default function Anomaly() {
    return (
        <>
            <NavigationBar />
            <div className="p-6 max-w-4xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">Anomalie Seite</h1>
                <p className="text-gray-600 mb-6">Hier kannst du später die Anomalien anschauen.</p>
            </div>
        </>
    );
}
