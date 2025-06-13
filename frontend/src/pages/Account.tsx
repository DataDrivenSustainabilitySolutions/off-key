import { NavigationBar } from "@/components/NavigationBar";

export default function AccountPage() {
    return (
        <>
            <NavigationBar />
            <div className="p-6 max-w-4xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">Account Einstellungen</h1>
                <p className="text-gray-600 mb-6">Hier kannst du deine persönlichen Einstellungen anpassen.</p>
            </div>
        </>
    );
}
