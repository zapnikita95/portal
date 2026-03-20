"""
Виджет-портал для рабочего стола с анимацией и drag & drop
"""

import tkinter as tk
from tkinter import ttk
import math
import threading
import time
import sys
import platform
from pathlib import Path

# Импорт основной логики из portal.py
try:
    from portal import PortalApp
except ImportError:
    print("Ошибка: не найден portal.py")
    sys.exit(1)


class PortalWidget:
    """Виджет-портал на рабочем столе"""
    
    def __init__(self, main_app: PortalApp):
        self.main_app = main_app
        self.root = tk.Toplevel() if hasattr(main_app, 'winfo_toplevel') else tk.Tk()
        self.root.title("🌀 Портал")
        
        # Настройка окна
        self.size = 200
        self.angle = 0
        self.animation_running = True
        
        # Позиция на рабочем столе (правый нижний угол)
        self.setup_window()
        
        # Canvas для анимации
        self.canvas = tk.Canvas(
            self.root,
            width=self.size,
            height=self.size,
            bg='black',
            highlightthickness=0
        )
        self.canvas.pack()
        
        # Настройка drag & drop
        self.setup_drag_drop()
        
        # Запуск анимации
        self.animate()
        
        # Переменная для хранения целевого IP
        self.target_ip = None
        
    def setup_window(self):
        """Настройка окна виджета"""
        # Прозрачность (работает на Windows и Linux)
        if platform.system() == 'Windows':
            try:
                self.root.attributes('-alpha', 0.85)
                self.root.attributes('-topmost', True)
            except:
                pass
        elif platform.system() == 'Darwin':  # macOS
            try:
                self.root.attributes('-alpha', 0.85)
                self.root.attributes('-topmost', True)
            except:
                pass
        else:  # Linux
            try:
                self.root.attributes('-alpha', 0.85)
                self.root.attributes('-topmost', True)
            except:
                pass
        
        # Убираем рамку окна
        self.root.overrideredirect(True)
        
        # Позиционирование (правый нижний угол)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = screen_width - self.size - 20
        y = screen_height - self.size - 80  # Учитываем панель задач
        
        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")
        
        # Сделать окно перетаскиваемым
        self.root.bind('<Button-1>', self.start_drag)
        self.root.bind('<B1-Motion>', self.on_drag)
        self.drag_start_x = 0
        self.drag_start_y = 0
        
        # Двойной клик для настроек
        self.root.bind('<Double-Button-1>', self.show_settings)
        
        # Правый клик для меню
        self.root.bind('<Button-3>', self.show_context_menu)
        
    def setup_drag_drop(self):
        """Настройка drag & drop для файлов"""
        # Windows с tkinterdnd2
        if platform.system() == 'Windows':
            try:
                import tkinterdnd2 as tkdnd
                self.dnd = tkdnd.DND_FUNC
                self.canvas.drop_target_register(tkdnd.DND_FILES)
                self.canvas.dnd_bind('<<Drop>>', self.on_file_drop)
                return
            except ImportError:
                pass  # Используем альтернативный метод
        
        # Альтернативный метод для всех платформ
        self.setup_drag_drop_alternative()
    
    def setup_drag_drop_alternative(self):
        """Альтернативный метод drag & drop через диалог"""
        # При клике на портал открываем диалог выбора файла
        self.canvas.bind('<Button-1>', lambda e: self.on_portal_click())
    
    def on_portal_click(self):
        """Обработка клика на портал"""
        from tkinter import filedialog
        files = filedialog.askopenfilenames(title="Выберите файлы для отправки")
        if files:
            self.send_files(files)
    
    def on_file_drop(self, event):
        """Обработка перетаскивания файла"""
        try:
            files = self.root.tk.splitlist(event.data)
            self.send_files(files)
        except Exception as e:
            print(f"Ошибка при обработке файлов: {e}")
    
    def send_files(self, files):
        """Отправка файлов через главное приложение"""
        if not self.target_ip:
            # Показываем диалог и ждем ввода IP
            dialog_result = []
            def set_ip(ip):
                dialog_result.append(ip)
            
            self.show_ip_dialog_sync(set_ip)
            if dialog_result:
                self.target_ip = dialog_result[0]
            else:
                return
        
        for filepath in files:
            if self.main_app and hasattr(self.main_app, 'send_file'):
                if hasattr(self.main_app, 'log'):
                    self.main_app.log(f"📤 Отправка через виджет: {Path(filepath).name}")
                threading.Thread(
                    target=self.main_app.send_file,
                    args=(filepath, self.target_ip),
                    daemon=True
                ).start()
    
    def show_ip_dialog_sync(self, callback):
        """Синхронный диалог для ввода IP"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройка получателя")
        dialog.geometry("300x150")
        dialog.attributes('-topmost', True)
        dialog.grab_set()  # Модальное окно
        
        label = tk.Label(dialog, text="Введите IP получателя:")
        label.pack(pady=10)
        
        ip_entry = tk.Entry(dialog, width=25)
        ip_entry.pack(pady=5)
        if self.target_ip:
            ip_entry.insert(0, self.target_ip)
        else:
            ip_entry.insert(0, "100.")
        ip_entry.focus()
        
        def save_ip():
            ip = ip_entry.get().strip()
            if ip:
                callback(ip)
            dialog.destroy()
        
        def on_enter(event):
            save_ip()
        
        ip_entry.bind('<Return>', on_enter)
        
        save_button = tk.Button(dialog, text="Сохранить", command=save_ip)
        save_button.pack(pady=10)
    
    def show_ip_dialog(self):
        """Диалог для ввода IP получателя"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройка получателя")
        dialog.geometry("300x150")
        dialog.attributes('-topmost', True)
        
        label = tk.Label(dialog, text="Введите IP получателя:")
        label.pack(pady=10)
        
        ip_entry = tk.Entry(dialog, width=25)
        ip_entry.pack(pady=5)
        if self.target_ip:
            ip_entry.insert(0, self.target_ip)
        else:
            ip_entry.insert(0, "100.")
        
        def save_ip():
            self.target_ip = ip_entry.get().strip()
            dialog.destroy()
        
        save_button = tk.Button(dialog, text="Сохранить", command=save_ip)
        save_button.pack(pady=10)
    
    def show_settings(self, event=None):
        """Показать настройки"""
        self.show_ip_dialog()
    
    def show_context_menu(self, event):
        """Показать контекстное меню"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Настройки IP", command=self.show_ip_dialog)
        menu.add_command(label="Скрыть", command=self.hide)
        menu.add_separator()
        menu.add_command(label="Выход", command=self.destroy)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    
    def start_drag(self, event):
        """Начало перетаскивания окна"""
        self.drag_start_x = event.x
        self.drag_start_y = event.y
    
    def on_drag(self, event):
        """Перетаскивание окна"""
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")
    
    def animate(self):
        """Анимация портала"""
        if not self.animation_running:
            return
        
        self.canvas.delete("all")
        
        center_x = self.size // 2
        center_y = self.size // 2
        radius = self.size // 2 - 20
        
        # Рисуем портал (вращающийся круг с эффектом)
        self.draw_portal(center_x, center_y, radius)
        
        self.angle += 0.1
        if self.angle >= 2 * math.pi:
            self.angle = 0
        
        self.root.after(16, self.animate)  # ~60 FPS
    
    def draw_portal(self, cx, cy, radius):
        """Рисование портала в стиле игры Portal"""
        # Внешний круг (синий)
        self.canvas.create_oval(
            cx - radius, cy - radius,
            cx + radius, cy + radius,
            outline='#00A8FF',
            width=4,
            fill='#001122'
        )
        
        # Внутренний круг (оранжевый) - вращается
        inner_radius = radius * 0.7
        points = []
        num_segments = 16
        
        for i in range(num_segments):
            angle = self.angle + (i * 2 * math.pi / num_segments)
            x = cx + inner_radius * math.cos(angle)
            y = cy + inner_radius * math.sin(angle)
            points.extend([x, y])
        
        if len(points) >= 6:
            self.canvas.create_polygon(
                points,
                outline='#FF6B35',
                fill='#331100',
                width=2
            )
        
        # Центральная точка
        self.canvas.create_oval(
            cx - 5, cy - 5,
            cx + 5, cy + 5,
            fill='#FF6B35',
            outline='#00A8FF'
        )
        
        # Эффект свечения (концентрические круги)
        for i in range(3):
            glow_radius = radius * (0.9 - i * 0.1)
            alpha = 0.3 - i * 0.1
            self.canvas.create_oval(
                cx - glow_radius, cy - glow_radius,
                cx + glow_radius, cy + glow_radius,
                outline='#00A8FF',
                width=1
            )
    
    def hide(self):
        """Скрыть виджет"""
        self.root.withdraw()
    
    def show(self):
        """Показать виджет"""
        self.root.deiconify()
    
    def destroy(self):
        """Уничтожить виджет"""
        self.animation_running = False
        self.root.destroy()


class GlobalHotkeyManager:
    """Менеджер глобальных горячих клавиш"""
    
    def __init__(self, widget: PortalWidget):
        self.widget = widget
        self.hotkey_thread = None
        self.running = False
        
    def start(self):
        """Запуск мониторинга горячих клавиш"""
        self.running = True
        self.hotkey_thread = threading.Thread(target=self.hotkey_loop, daemon=True)
        self.hotkey_thread.start()
    
    def stop(self):
        """Остановка мониторинга"""
        self.running = False
    
    def hotkey_loop(self):
        """Цикл мониторинга горячих клавиш"""
        try:
            import keyboard
            
            # Определяем платформу
            if platform.system() == 'Windows':
                # Ctrl+Alt+P на Windows
                keyboard.add_hotkey('ctrl+alt+p', self.toggle_widget)
            elif platform.system() == 'Darwin':  # macOS
                # На Mac используем Cmd+Option+P (Fn+P сложно реализовать)
                # Альтернатива: можно использовать pynput для более точного контроля
                try:
                    keyboard.add_hotkey('cmd+option+p', self.toggle_widget)
                except:
                    # Если не работает, пробуем через pynput
                    self.setup_mac_hotkey()
            else:  # Linux
                keyboard.add_hotkey('ctrl+alt+p', self.toggle_widget)
            
            # Держим поток живым
            while self.running:
                time.sleep(0.1)
                
        except ImportError:
            print("Библиотека keyboard не установлена. Горячие клавиши недоступны.")
            # Пробуем использовать pynput как альтернативу
            self.setup_pynput_hotkey()
        except Exception as e:
            print(f"Ошибка в горячих клавишах: {e}")
            self.setup_pynput_hotkey()
    
    def setup_mac_hotkey(self):
        """Настройка горячих клавиш для Mac через pynput"""
        try:
            from pynput import keyboard as pynput_keyboard
            
            def on_press(key):
                try:
                    # Проверяем комбинацию Cmd+Option+P
                    # На Mac это сложнее, используем Ctrl+Option+P
                    if hasattr(key, 'char') and key.char == 'p':
                        modifiers = []
                        # Проверяем модификаторы через listener
                        pass
                except:
                    pass
            
            # Это требует более сложной реализации
            # Пока используем keyboard библиотеку
        except:
            pass
    
    def setup_pynput_hotkey(self):
        """Альтернативная настройка через pynput"""
        try:
            from pynput import keyboard as pynput_keyboard
            
            # Создаем комбинацию клавиш
            if platform.system() == 'Windows':
                combo = {pynput_keyboard.Key.ctrl, pynput_keyboard.Key.alt, pynput_keyboard.KeyCode.from_char('p')}
            elif platform.system() == 'Darwin':
                combo = {pynput_keyboard.Key.cmd, pynput_keyboard.Key.alt, pynput_keyboard.KeyCode.from_char('p')}
            else:
                combo = {pynput_keyboard.Key.ctrl, pynput_keyboard.Key.alt, pynput_keyboard.KeyCode.from_char('p')}
            
            pressed = set()
            
            def on_press(key):
                pressed.add(key)
                if combo.issubset(pressed):
                    self.toggle_widget()
            
            def on_release(key):
                try:
                    pressed.discard(key)
                except:
                    pass
            
            listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.start()
        except Exception as e:
            print(f"Не удалось настроить горячие клавиши через pynput: {e}")
    
    def toggle_widget(self):
        """Переключение видимости виджета"""
        try:
            if self.widget.root.winfo_viewable():
                self.widget.hide()
            else:
                self.widget.show()
        except:
            pass


if __name__ == "__main__":
    # Для тестирования виджета отдельно
    root = tk.Tk()
    root.withdraw()  # Скрываем главное окно
    
    # Создаем фиктивное главное приложение
    class FakeApp:
        def send_file(self, filepath, target_ip):
            print(f"Отправка {filepath} на {target_ip}")
    
    fake_app = FakeApp()
    widget = PortalWidget(fake_app)
    
    # Запускаем горячие клавиши
    hotkey_manager = GlobalHotkeyManager(widget)
    hotkey_manager.start()
    
    root.mainloop()
