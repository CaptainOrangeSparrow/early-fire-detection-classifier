import asyncio
import threading
from telemetry.Async_class_telemetry import Telemetry


class TelemetryWrapper:
    def __init__(self, auto_switch=5, debug=True, rgb_cam=None, ir_cam=None, adc_module=None):
        self.auto_switch = auto_switch
        self.debug = debug

        self._thread = None
        self._loop = None
        self._task = None
        self._telemetry = None
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._exception = None
        self.rgb_cam = rgb_cam
        self.ir_cam = ir_cam
        self.adc_module = adc_module


    async def _run_async(self):
        self._telemetry = Telemetry(auto_switch=self.auto_switch, debug=self.debug, rgb_cam=self.rgb_cam, ir_cam=self.ir_cam, adc_module=self.adc_module)
        self._started.set()

        try:
            await self._telemetry.execute()
        finally:
            try:
                if hasattr(self._telemetry, "display"):
                    self._telemetry.display.cleanup()
            finally:
                self._stopped.set()

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._task = self._loop.create_task(self._run_async())
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._exception = e
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                try:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                except Exception:
                    pass
            self._loop.close()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("TelemetrySubsystem is already running")

        self._started.clear()
        self._stopped.clear()
        self._exception = None

        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        self._started.wait()

    def stop(self, timeout=5.0):
        if self._loop is None or self._task is None:
            return

        def _cancel_task():
            if self._task and not self._task.done():
                self._task.cancel()

        self._loop.call_soon_threadsafe(_cancel_task)

        self._stopped.wait(timeout=timeout)

        if self._thread is not None:
            self._thread.join(timeout=timeout)

        if self._exception is not None:
            raise self._exception

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()
