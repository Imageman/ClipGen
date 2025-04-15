from loguru import logger
import time
import threading
import traceback
from typing import Optional, Callable, Tuple
import pyperclip
from PIL import ImageGrab, Image
import win32gui
import win32con
import ctypes

# Windows message for clipboard update
WM_CLIPBOARDUPDATE = 0x031D


class GlobalClipboardMonitor:
    """
    A class that uses the Windows API (AddClipboardFormatListener) to monitor
    clipboard changes globally (even when the application window is not active).

    When the clipboard changes, it checks if the change represents a repeated copy
    (i.e. if the same content is copied within a given threshold, default 0.5 seconds).
    If so, it triggers the provided command callback with the clipboard text (or None if not text)
    and clipboard image (or None if not an image).

    Attributes:
    -----------
    command_callback : Callable[[Optional[str], Optional[Image.Image]], None]
        A callback function to be executed on a repeated copy event.
    repeat_threshold : float
        The time threshold (in seconds) to consider a copy event as a repeat.
    """

    def __init__(
            self,
            command_callback: Optional[Callable[[Optional[str], Optional[Image.Image]], None]] = None,
            repeat_threshold: float = 0.5
    ) -> None:
        """
        Initialize the GlobalClipboardMonitor instance.

        Parameters:
        -----------
        command_callback : Optional[Callable[[Optional[str], Optional[Image.Image]], None]]
            Function to be called on a repeated copy event. If None, a default do_command is used.
        repeat_threshold : float
            Time threshold in seconds to detect repeated copy events.
        """
        self.command_callback = command_callback if command_callback is not None else self.do_command
        self.repeat_threshold = repeat_threshold

        # Variables to track clipboard state and timing
        self._last_copy_time: float = 0.0
        self._last_clipboard_content: Optional[str] = ''

        # Handle to the hidden window that receives clipboard messages
        self.hwnd: Optional[int] = None
        self._message_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _create_window(self) -> None:
        """
        Creates a hidden window and registers it to receive WM_CLIPBOARDUPDATE messages.
        """
        # Define window class
        wndclass = win32gui.WNDCLASS()
        self.class_name = "GlobalClipboardMonitorWindow"
        wndclass.lpszClassName = self.class_name
        wndclass.lpfnWndProc = self._wnd_proc  # Window procedure callback

        try:
            class_atom = win32gui.RegisterClass(wndclass)
        except Exception as e:
            logger.error(f"Failed to register window class: {e}")
            logger.debug(traceback.format_exc())
            return

        # Create an invisible window
        self.hwnd = win32gui.CreateWindowEx(
            0,
            class_atom,
            self.class_name,
            0,  # Window style: no style needed
            0, 0, 0, 0,  # x, y, width, height (invisible)
            0,
            0,
            0,
            None
        )

        if self.hwnd:
            # Используем ctypes для вызова AddClipboardFormatListener из user32.dll
            if ctypes.windll.user32.AddClipboardFormatListener(self.hwnd):
                logger.debug("Clipboard listener registered successfully.")
            else:
                logger.error("Failed to register clipboard listener.")

    def _wnd_proc(self, hwnd: int, msg: int, wparam, lparam) -> int:
        """
        Window procedure to handle Windows messages.
        """
        if msg == WM_CLIPBOARDUPDATE:
            logger.debug("WM_CLIPBOARDUPDATE received.")
            self._handle_clipboard_update()
            return 0
        elif msg == win32con.WM_DESTROY:
            win32gui.RemoveClipboardFormatListener(hwnd)
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _handle_clipboard_update(self) -> None:
        """
        Handle a clipboard update event.

        Reads the clipboard content (text and image) and checks if this update represents
        a repeated copy (i.e., the same content is copied within the repeat_threshold).
        If so, triggers the command callback.
        """
        try:
            current_time = time.time()
            # Get clipboard text
            clipboard_text = pyperclip.paste()
            # Determine if the text is valid (non-empty string), else set to None
            text = clipboard_text if isinstance(clipboard_text, str) and clipboard_text.strip() else None

            # Get clipboard image (if any)
            clip_img = ImageGrab.grabclipboard()
            image = clip_img if isinstance(clip_img, Image.Image) else None

            logger.debug(
                f"Clipboard update: text={'present' if text else 'None'}, image={'present' if image else 'None'}")

            if (self._last_clipboard_content is not None and
                    (current_time - self._last_copy_time < self.repeat_threshold) and
                    (current_time - self._last_copy_time > 0.09) and # в некоторых программах двойное копирование
                    (clipboard_text == self._last_clipboard_content)):
                logger.debug("Repeated copy detected. Triggering command callback.")
                self.command_callback(text, image)
                self._last_copy_time = current_time+4 # ставим игнорирование на 4 секунды
                self._last_clipboard_content=''
            elif current_time> self._last_copy_time:
                self._last_copy_time = current_time
                self._last_clipboard_content = clipboard_text
        except Exception as e:
            logger.error(f"Error handling clipboard update: {e}")
            logger.debug(traceback.format_exc())

    def do_command(self, text: Optional[str], image: Optional[Image.Image]) -> None:
        """
        Default command executed on a repeated copy event.

        Parameters:
        -----------
        text : Optional[str]
            The clipboard text, or None if not available.
        image : Optional[Image.Image]
            The clipboard image, or None if not available.
        """
        logger.info(f"do_command executed with text: {text} and image: {'present' if image else 'None'}")

    def _message_loop(self) -> None:
        """
        Runs the Windows message loop.
        This loop will block until WM_QUIT is posted.
        """
        logger.debug("Entering message loop.")
        try:
            while not self._stop_event.is_set():
                win32gui.PumpWaitingMessages()
                time.sleep(0.01)  # Короткая задержка для снижения нагрузки
        except Exception as e:
            logger.error(f"Error in message loop: {e}")
            logger.debug(traceback.format_exc())

    def start(self) -> None:
        """
        Starts the clipboard monitor by creating the hidden window and running the message loop in a separate thread.
        """
        self._stop_event.clear()
        self._message_thread = threading.Thread(target=self._run, daemon=True)
        self._message_thread.start()
        logger.info("GlobalClipboardMonitor started.")

    def _run(self) -> None:
        """
        Internal method to create the window and start the message loop.
        """
        self._create_window()
        if self.hwnd:
            self._message_loop()

    def stop(self) -> None:
        """
        Stops the clipboard monitor by posting a WM_CLOSE message to the hidden window and stopping the message loop.
        """
        self._stop_event.set()
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        if self._message_thread is not None:
            self._message_thread.join()
        logger.info("GlobalClipboardMonitor stopped.")


# Example usage
if __name__ == "__main__":
    def custom_command(text: Optional[str], image: Optional[Image.Image]) -> None:
        """
        Custom command to be executed when a repeated copy is detected.
        """
        logger.info(f"Custom command triggered with text: {text} and image: {'present' if image else 'None'}")


    monitor = GlobalClipboardMonitor(command_callback=custom_command, repeat_threshold=0.5)
    monitor.start()

    logger.info("GlobalClipboardMonitor is running. Copy content repeatedly within 0.5 seconds to trigger the command.")
    logger.info("Press Ctrl+C in the console to exit.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        logger.debug(traceback.format_exc())
        monitor.stop()
