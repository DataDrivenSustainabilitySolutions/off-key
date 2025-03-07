import { buttonVariants } from "@/components/ui/button";
import { GitHubLogoIcon } from "@radix-ui/react-icons";

export const Hero = () => {
    return (
        <section className="container flex flex-col items-center justify-center text-center py-20 md:py-32 gap-10">
            <div className="space-y-6 max-w-4xl">
                <main className="text-9xl md:text-6xl font-bold">
                    <h1 className="inline">
                        <span className="inline bg-gradient-to-r from-[#355C7D] to-[#C06C84] text-transparent bg-clip-text">
                            off/key
                        </span>{" "}
                        <br />
                    </h1>{" "}
                </main>

                <p className="text-xl text-muted-foreground md:w-10/12 whitespace-nowrap mx-auto">
                    Real-time Anomaly Detection
                </p>

                <div className="flex flex-col md:flex-row items-center justify-center space-y-4 md:space-y-0 md:space-x-4">
                    <a
                        rel="noreferrer noopener"
                        href="/login"
                        target="_blank"
                        className={`w-full md:w-auto px-6 py-3 bg-gradient-to-r from-[#355C7D] to-[#C06C84] text-white transition-all duration-200 ease-in-out ${buttonVariants({
                            variant: "outline",
                        })} hover:bg-gradient-to-r hover:from-[#4D7D91] hover:to-[#D37797] active:bg-gradient-to-r active:from-[#4D7D91] active:to-[#D37797] hover:text-white active:text-white`}
                    >
                        Get Started
                    </a>

                    <a
                        rel="noreferrer noopener"
                        href="https://github.com/OliverHennhoefer/off-key"
                        target="_blank"
                        className={`w-full md:w-auto px-6 py-3 ${buttonVariants({
                            variant: "outline",
                        })}`}
                    >
                        Github Repository
                        <GitHubLogoIcon className="ml-2 w-5 h-5" />
                    </a>
                </div>
            </div>
        </section>
    );
};
