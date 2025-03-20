import sys
import os
import logging
import json
import time
import winsound
from multiprocessing import Queue
from multiprocessing.queues import Empty
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import threading
from PIL import ImageGrab
import pyperclip
import google.generativeai as genai
from dotenv import load_dotenv
from google.generativeai import GenerationConfig
import win32api
import win32con
import win32gui
from pynput import keyboard as pkb
import customtkinter as ctk
from tkinter import Text, Menu

# Настройка логирования
logger = logging.getLogger()
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(console_handler)

# Глобальная переменная для текущей конфигурации
current_config = None

# Загрузка доступных конфигураций
if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(__file__)

config_files = [f for f in os.listdir(base_path) if f.startswith('config_') and f.endswith('.json')]
languages = [f.replace('config_', '').replace('.json', '').upper() for f in config_files]
language_configs = {}
for config_file in config_files:
    lang_code = config_file.replace('config_', '').replace('.json', '').upper()
    with open(os.path.join(base_path, config_file), 'r', encoding='utf-8') as f:
        language_configs[lang_code] = json.load(f)

# Устанавливаем начальный язык (по умолчанию RU, если доступен)
if "RU" in languages:
    current_config = language_configs["RU"]
else:
    current_config = list(language_configs.values())[0]

load_dotenv('.env')
# API_KEY = current_config['api_key']
API_KEY = os.getenv('gemini_api_key')
if not API_KEY:
    logger.error("Error: API key not found in configuration")
    sys.exit(1)

# Конфигурация Gemini
genai.configure(api_key=API_KEY)
MODEL_NAME = "models/gemini-2.0-flash-exp"
model = genai.GenerativeModel(model_name=MODEL_NAME)
executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="GeminiWorker")

# Отслеживание состояния клавиш
key_states = {key['combination'].lower(): False for key in current_config['hotkeys']}
key_states['ctrl'] = False

def call_with_timeout(func, timeout, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="TimeoutExecutor") as temp_executor:
        future = temp_executor.submit(func, *args, **kwargs)
        return future.result(timeout=timeout)

def process_text_with_gemini(original_text: str, action: str, prompt: str) -> str:
    try:
        full_prompt = prompt + original_text
        def generate():
            return model.generate_content(full_prompt, generation_config=GenerationConfig(temperature=0.1, max_output_tokens=2048))

        start_time = time.time()
        response = call_with_timeout(generate, 45)
        elapsed_time = time.time() - start_time
        logger.info(f"[{action}] Completed - executed in {elapsed_time:.2f} seconds")
        if response and response.text:
            logger.info(f"[{action}] {response.text.strip()}")
        return response.text.strip() if response and response.text else ""
    except FutureTimeoutError:
        logger.error(f"[{action}] Timeout exceeded waiting for Gemini response")
        return ""
    except Exception as e:
        logger.error(f"[{action}] Error querying Gemini: {e}")
        return ""

def handle_image_analysis(action: str, prompt: str):
    try:
        image = ImageGrab.grabclipboard()
        if image is None:
            logger.warning(f"[{action}] Clipboard does not contain an image")
            return
        
        def generate():
            return model.generate_content(contents=[prompt, image], generation_config=GenerationConfig(temperature=0.1, max_output_tokens=2048))

        start_time = time.time()
        response = call_with_timeout(generate, 45)
        elapsed_time = time.time() - start_time
        logger.info(f"[{action}] Image analysis completed - executed in {elapsed_time:.2f} seconds")
        if response and response.text:
            logger.info(f"[{action}] {response.text.strip()}")
            pyperclip.copy(response.text.strip())
            time.sleep(0.3)
            win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
            win32api.keybd_event(ord('V'), 0, 0, 0)
            time.sleep(0.1)
            win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
            win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception as ex:
        logger.error(f"[{action}] Error during image analysis: {ex}")

def _handle_text_operation(operation_func, action, prompt):
    try:
        # Отжимаем Alt, если он нажат
        if win32api.GetKeyState(win32con.VK_MENU) < 0:  # VK_MENU - это Alt
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)  # Короткая пауза для корректного отжатия
        winsound.PlaySound("rsc\in.wav ", winsound.SND_FILENAME)
            
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord('C'), 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(ord('C'), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.3)

        original_text = pyperclip.paste()
        if not original_text.strip():
            logger.warning(f"[{action}] Clipboard is empty after copying")
            return

        processed_text = operation_func(original_text, action, prompt)
        pyperclip.copy(processed_text)

        time.sleep(0.3)
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord('V'), 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        winsound.PlaySound("rsc\out.wav", winsound.SND_FILENAME)
    except Exception as ex:
        logger.error(f"[{action}] Error: {ex}")

def on_press(key, queue):
    global key_states
    try:
        key_str = str(key).lower().replace("key.", "")
        # print(key_str)
        
        # Обрабатываем нажатие Ctrl и Alt
        if key_str in ["ctrl_l", "ctrl_r"]:
            key_states['ctrl'] = True
            return
        elif key_str in ["alt_l", "alt_r", "alt_gr"]:
            key_states['alt'] = True
            return

        # Проверяем, какие горячие клавиши настроены
        for hotkey in current_config['hotkeys']:
            combo = hotkey['combination'].lower()
            action = hotkey['description'][1]
            
            # Проверяем, содержится ли key_str в комбинации
            if key_str in combo and (
                ("ctrl" in combo and key_states.get('ctrl')) or
                ("alt" in combo and key_states.get('alt'))
            ):
                logger.info(f"[{action}] {hotkey['description'][0]} - {time.strftime('%H:%M:%S')}")
                queue.put(action)
                
                # Сбрасываем состояние клавиш после выполнения действия
                key_states['ctrl'] = False
                key_states['alt'] = False
                key_states[combo] = False
                break
    except Exception as e:
        logger.error(f"Error in on_press: {e}")

def on_release(key, queue):
    global key_states
    try:
        key_str = str(key).lower().replace("key.", "")

        # Сбрасываем состояние клавиши при отпускании
        if key_str in ["ctrl_l", "ctrl_r"]:
            key_states['ctrl'] = False
        elif key_str in ["alt_l", "alt_r", "alt_gr"]:
            key_states['alt'] = False

    except Exception as e:
        logger.error(f"Error in on_release: {e}")


def hotkey_listener(queue: Queue, stop_event: threading.Event):
    try:
        logger.info("Starting hotkey listener")
        with pkb.Listener(on_press=lambda k: on_press(k, queue), on_release=lambda k: on_release(k, queue)) as listener:
            stop_event.wait()
            listener.stop()
        logger.info("Hotkey listener stopped")
    except Exception as e:
        logger.error(f"Error in listener process: {e}")

class App(ctk.CTk):
    def __init__(self, queue, listener_thread, stop_event):
        super().__init__()
        logger.info("Initializing application")
        self.queue = queue
        self.listener_thread = listener_thread
        self.stop_event = stop_event
        self.title("ClipGen")
        self.geometry("554x632")
        self.resizable(True, True)
        self.configure(fg_color="#1e1e1e")
        self.minsize(400, 300)
        self._last_update = 0

        # Titlebar
        self.titlebar = ctk.CTkFrame(self, height=30, fg_color="#1e1e1e", corner_radius=10)
        self.titlebar.pack(fill="x", padx=10, pady=5)
        self.titlebar.pack_propagate(False)

        self.tooltip_label = ctk.CTkLabel(
            self.titlebar, text="", fg_color="transparent", text_color="#FFFFFF", padx=5, pady=2
        )
        self.tooltip_label.pack(side="left")

        self.lang_combobox = ctk.CTkComboBox(
            self.titlebar, values=languages, command=self.change_language,
            fg_color='#333333', text_color='#ffffff', dropdown_fg_color='#333333',
            dropdown_text_color='#ffffff', width=100
        )
        self.lang_combobox.pack(side='right', padx=5, pady=5)
        self.lang_combobox.set("RU" if "RU" in languages else languages[0])

        self.titlebar.bind("<Button-1>", self.start_drag)
        self.titlebar.bind("<B1-Motion>", self.drag)

        # Buttons frame
        self.button_frame = ctk.CTkFrame(self, fg_color="#2e2e2e", corner_radius=10)
        self.button_frame.pack(fill="x", padx=10, pady=5)
        self.button_inner_frame = ctk.CTkFrame(self.button_frame, fg_color="#2e2e2e", corner_radius=10)
        self.button_inner_frame.pack(fill="both", expand=True, padx=2, pady=2)

        self.action_colors = {hotkey['description'][1]: hotkey['log_color'] for hotkey in current_config['hotkeys']}
        self.action_colors["restart"] = "#FFFFFF"
        self.button_configs = [(hotkey['description'][0], hotkey['description'][1], hotkey['description'][2]) 
                              for hotkey in current_config['hotkeys']]
        restart_text = current_config.get('buttons', {}).get('restart', "Restart")
        restart_tooltip = current_config.get('buttons', {}).get('restart_tooltip', "Restarts the application.")
        self.button_configs.append((restart_text, "restart", restart_tooltip))

        self.buttons = []
        for idx, (text, action, tooltip) in enumerate(self.button_configs):
            hover_color = self.action_colors[action] if action != "restart" else "#FF9999"
            btn = ctk.CTkButton(
                self.button_inner_frame, text=text, fg_color="#333333", hover_color=hover_color,
                text_color=self.action_colors[action], corner_radius=8,
                command=lambda a=action: self.process_action(a)
            )
            btn.grid(row=idx, column=0, padx=5, pady=5, sticky="ew")
            btn.bind("<Enter>", lambda e, t=tooltip, a=action, b=btn: self.show_tooltip(t, a, b))
            btn.bind("<Leave>", lambda e, b=btn: self.hide_tooltip(b))
            self.buttons.append(btn)

        # Log area
        self.log_frame = ctk.CTkScrollableFrame(
            self, fg_color="#2e2e2e", scrollbar_button_color="#252525",
            scrollbar_button_hover_color="#555555", corner_radius=10
        )
        self.log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_area = Text(
            self.log_frame, wrap="word", font=("Consolas", 14), bg="#2e2e2e", fg="#FFFFFF",
            insertbackground="#FFFFFF", borderwidth=0, highlightthickness=0
        )
        self.log_area.pack(fill="both", expand=True)

        self.log_menu = Menu(self.log_area, tearoff=0)
        self.log_menu.add_command(label="Copy", command=self.copy_log)
        self.log_area.bind("<Button-3>", self.show_log_menu)
        self.log_area.bind("<Control-c>", self.copy_log)

        class LogHandler(logging.Handler):
            def __init__(self, text_widget, action_colors):
                super().__init__()
                self.text_widget = text_widget
                self.action_colors = action_colors
                self.text_widget.tag_configure("INFO", foreground="#FFFFFF")
                self.text_widget.tag_configure("WARNING", foreground="#FFD700")
                self.text_widget.tag_configure("ERROR", foreground="#FF4500")
                for action, color in action_colors.items():
                    self.text_widget.tag_configure(action, foreground=color)

            def emit(self, record):
                msg = record.msg
                if any(debug_msg in msg for debug_msg in ["Starting action", "Received event", "Processing action"]):
                    return
                self.text_widget.configure(state='normal')
                level_tag = record.levelname
                action_tag = next((action for action in self.action_colors.keys() if f"[{action}]" in msg), None)
                if action_tag:
                    msg_cleaned = msg.replace(f"[{action_tag}] ", "")
                    self.text_widget.insert("end", msg_cleaned + '\n', (level_tag, action_tag))
                else:
                    self.text_widget.insert("end", msg + '\n', level_tag)
                self.text_widget.see("end")
                self.text_widget.configure(state='normal')

        log_handler = LogHandler(self.log_area, self.action_colors)
        log_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(log_handler)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Configure>", self.debounce_update_layout)
        logger.info("Starting queue check")
        self.check_queue()
        logger.info("Interface initialized")
        self.deiconify()
        self.lift()
        self.focus_force()

    def start_drag(self, event):
        self.x = event.x
        self.y = event.y

    def drag(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")
        self.update_idletasks()

    def debounce_update_layout(self, event):
        current_time = time.time()
        if current_time - self._last_update > 0.2:
            self._last_update = current_time
            self.update_button_layout()
        else:
            if not hasattr(self, '_scheduled_update'):
                self._scheduled_update = self.after(200, self._update_layout_once)

    def _update_layout_once(self):
        self.update_button_layout()
        if hasattr(self, '_scheduled_update'):
            del self._scheduled_update

    def update_button_layout(self):
        width = self.button_inner_frame.winfo_width()
        if width <= 0:
            return

        for widget in self.button_inner_frame.winfo_children():
            widget.grid_forget()

        buttons_per_row = []
        current_row = []
        for btn in self.buttons:
            btn_width = btn.winfo_reqwidth()
            if (len(current_row) > 0 and 
                sum(b.winfo_reqwidth() for b in current_row) + btn_width + (len(current_row) + 1) * 10 > width):
                buttons_per_row.append(current_row)
                current_row = [btn]
            else:
                current_row.append(btn)
        if current_row:
            buttons_per_row.append(current_row)

        for row_idx, row in enumerate(buttons_per_row):
            for col_idx, btn in enumerate(row):
                btn.grid(row=row_idx, column=col_idx, padx=5, pady=5, sticky="ew")
            for col_idx in range(len(row)):
                self.button_inner_frame.grid_columnconfigure(col_idx, weight=1)

    def show_tooltip(self, text, action, button):
        if hasattr(self, '_tooltip_timer'):
            self.after_cancel(self._tooltip_timer)
        self._tooltip_timer = self.after(150, lambda: self._show_tooltip(text, action, button))

    def _show_tooltip(self, text, action, button):
        if not hasattr(self, '_active_button') or self._active_button != button:
            if hasattr(self, '_active_button'):
                self._hide_tooltip(self._active_button)
            self.tooltip_label.configure(text=text)
            button._original_fg_color = button.cget("fg_color")
            button._original_text_color = button.cget("text_color")
            button.configure(fg_color=self.action_colors[action], text_color="#333333")
            self._active_button = button

    def hide_tooltip(self, button):
        if hasattr(self, '_tooltip_timer'):
            self.after_cancel(self._tooltip_timer)
        self._tooltip_timer = self.after(150, lambda: self._hide_tooltip(button))

    def _hide_tooltip(self, button):
        if hasattr(self, '_active_button') and self._active_button == button:
            self.tooltip_label.configure(text="")
            if hasattr(button, '_original_fg_color'):
                button.configure(fg_color=button._original_fg_color, text_color=button._original_text_color)
            del self._active_button

    def process_action(self, action):
        logger.info(f"Processing action: {action}")
        self.queue.put(action)

    def change_language(self, lang):
        global current_config, key_states
        current_config = language_configs[lang.upper()]
        key_states = {key['combination'].lower(): False for key in current_config['hotkeys']}
        key_states['ctrl'] = False
        self.action_colors = {hotkey['description'][1]: hotkey['log_color'] for hotkey in current_config['hotkeys']}
        self.action_colors["restart"] = "#FFFFFF"
        self.button_configs = [(hotkey['description'][0], hotkey['description'][1], hotkey['description'][2]) 
                              for hotkey in current_config['hotkeys']]
        restart_text = current_config.get('buttons', {}).get('restart', "Restart")
        restart_tooltip = current_config.get('buttons', {}).get('restart_tooltip', "Restarts the application.")
        self.button_configs.append((restart_text, "restart", restart_tooltip))
        for idx, (text, action, tooltip) in enumerate(self.button_configs):
            self.buttons[idx].configure(text=text)
            self.buttons[idx].unbind("<Enter>")
            self.buttons[idx].unbind("<Leave>")
            self.buttons[idx].bind("<Enter>", lambda e, t=tooltip, a=action, b=self.buttons[idx]: self.show_tooltip(t, a, b))
            self.buttons[idx].bind("<Leave>", lambda e, b=self.buttons[idx]: self.hide_tooltip(b))
            self.buttons[idx].configure(text_color=self.action_colors[action], 
                                       hover_color="#FF9999" if action == "restart" else self.action_colors[action])
        logger.info(f"Language changed to {lang}")

    def check_queue(self):
        def queue_worker():
            while not self.stop_event.is_set():
                try:
                    event = self.queue.get_nowait()
                    logger.info(f"Received event from queue: {event}")
                    actions = {
                        hotkey['description'][1]: lambda act=hotkey['description'][1], pr=hotkey['prompt']: _handle_text_operation(process_text_with_gemini, act, pr)
                        for hotkey in current_config['hotkeys'] if hotkey['description'][1] != 'image'
                    }
                    actions['image'] = lambda act='image', pr=current_config['hotkeys'][-1]['prompt']: handle_image_analysis(act, pr)
                    actions['restart'] = lambda: os.execl(sys.executable, sys.executable, *sys.argv)
                    
                    if event in actions:
                        logger.info(f"Starting action: {event}")
                        threading.Thread(target=actions[event], args=(), daemon=True).start()
                except Empty:
                    time.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error processing queue: {e}")
        
        threading.Thread(target=queue_worker, daemon=True).start()

    def show_log_menu(self, event):
        self.log_menu.post(event.x_root, event.y_root)

    def copy_log(self, event=None):
        selected_text = self.log_area.selection_get()
        if selected_text:
            self.clipboard_clear()
            self.clipboard_append(selected_text)
        return "break"

    def on_closing(self):
        logger.info("Closing program...")
        global executor
        executor.shutdown(wait=True, cancel_futures=True)
        if self.listener_thread.is_alive():
            self.stop_event.set()
            self.listener_thread.join(timeout=1.0)
            time.sleep(0.5)
        self.quit()
        self.destroy()
        sys.exit(0)  # этот вызов для немедленного завершения скрипта

def main():
    logger.info("Main process started.")
    event_queue = Queue()
    stop_event = threading.Event()
    listener_thread = threading.Thread(target=hotkey_listener, args=(event_queue, stop_event), daemon=True)
    listener_thread.start()
    try:
        app = App(event_queue, listener_thread, stop_event)
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Closing program by Ctrl+C...")
        executor.shutdown(wait=True, cancel_futures=True)
        if listener_thread.is_alive():
            stop_event.set()
            listener_thread.join(timeout=1.0)
        sys.exit(0)
    logger.info("Program completed after mainloop")

if __name__ == "__main__":
    main()