import sys
import asyncio
import logging
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QObject

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

try:
    from bot.ui.main_window import MainWindow
    # signals are connected within MainWindow to its views
    # from bot.ui.qt_signals import signals
    from bot.ui.bot_controller import BotController
    from bot.core.logger_setup import setup_logger
    from bot.core.config_loader import load_api_keys, load_log_level
except ImportError as e:
    logging.basicConfig(level=logging.INFO)
    logging.error(f"GUILauncher ImportError: {e}. Critical components not found. Run from project root or check PYTHONPATH.")
    sys.exit(1)

backend_controller_instance: Optional[BotController] = None
main_event_loop: Optional[asyncio.AbstractEventLoop] = None

def qt_event_loop_integration():
    global main_event_loop
    if main_event_loop is None:
        logging.error("Asyncio event loop not set for qt_event_loop_integration.")
        return
    poller_logger = logging.getLogger('algo_trader_bot.QtPoller')
    def poller():
        if main_event_loop and not main_event_loop.is_closed():
            main_event_loop.call_soon(main_event_loop.stop)
            main_event_loop.run_forever()
            QTimer.singleShot(10, poller)
        else: poller_logger.info("Asyncio event loop closed. Poller stopped.")

    if not hasattr(qt_event_loop_integration, "poller_started"):
        QTimer.singleShot(0, poller); setattr(qt_event_loop_integration, "poller_started", True)
        poller_logger.info("Asyncio/Qt event loop integration poller started.")

# Removed connect_ui_signals function as MainWindow._connect_global_signals handles this now.

def main_gui():
    dotenv_path = os.path.join(PROJECT_ROOT, '.env')
    log_level = load_log_level(env_file_path=dotenv_path)
    main_logger = setup_logger(level=log_level, log_file="gui_bot_activity.log", log_directory=os.path.join(PROJECT_ROOT, "logs", "gui"))
    main_logger.info("GUI Launcher: Application starting...")

    MainWindow.logger = main_logger.getChild("MainWindow")

    app = QApplication(sys.argv)

    global main_event_loop
    if sys.platform == "win32" and sys.version_info >= (3,8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_event_loop)

    qt_event_loop_integration()

    global backend_controller_instance
    backend_controller_instance = BotController()
    backend_controller_instance.loop = main_event_loop

    main_logger.info("Scheduling BotController async setup...")
    api_key, api_secret = load_api_keys(env_file_path=dotenv_path, use_testnet=True)
    asyncio.ensure_future(backend_controller_instance.async_setup(api_key, api_secret, use_testnet=True), loop=main_event_loop)

    window = MainWindow(backend_controller=backend_controller_instance)

    # MainWindow._connect_global_signals() is called in its __init__
    # It connects all necessary global signals to its views' slots.

    window.aboutToClose.connect(lambda: asyncio.ensure_future(backend_controller_instance.shutdown(), loop=main_event_loop)) # type: ignore

    window.show()
    main_logger.info("MainWindow shown.")

    # Trigger initial data load for views that need it, after UI is shown
    async def initial_ui_data_loads():
        await asyncio.sleep(1) # Ensure backend_controller.async_setup has progressed
        if backend_controller_instance:
            if hasattr(window, 'orders_positions_view') and window.orders_positions_view and hasattr(window.orders_positions_view, 'load_initial_data'):
                main_logger.info("Triggering initial data load for Orders & Positions view.")
                window.orders_positions_view.load_initial_data()
            if hasattr(window, 'chart_view') and window.chart_view and hasattr(window.chart_view, 'load_initial_chart_data'):
                main_logger.info("Triggering initial data load for Chart view.")
                window.chart_view.load_initial_chart_data()
            # Add other views' initial loads here if necessary
        else:
            main_logger.warning("Backend controller not ready for initial UI data loads.")

    asyncio.ensure_future(initial_ui_data_loads(), loop=main_event_loop)

    exit_code = app.exec()

    main_logger.info("GUI event loop finished. Initiating backend shutdown...")
    if backend_controller_instance:
        if main_event_loop and not main_event_loop.is_closed():
             shutdown_task = main_event_loop.create_task(backend_controller_instance.shutdown())
             try:
                 main_event_loop.run_until_complete(shutdown_task)
                 pending = asyncio.all_tasks(loop=main_event_loop)
                 if pending:
                    main_event_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
             except Exception as e_loop_shutdown:
                 main_logger.error(f"Error during asyncio shutdown: {e_loop_shutdown}")
             finally:
                 main_event_loop.close()
        else:
            asyncio.run(backend_controller_instance.shutdown())

    main_logger.info("Application shutdown complete.")
    sys.exit(exit_code)

if __name__ == '__main__':
    main_gui()
```
