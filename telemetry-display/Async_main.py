import asyncio
from Async_class_telemetry import Telemetry


async def main():

    telemetry = Telemetry(auto_switch=5, debug=True)

    try:

        await telemetry.execute()

    except KeyboardInterrupt:

        telemetry.display.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt as e:
        print(f"\nProgram Stopped by User")