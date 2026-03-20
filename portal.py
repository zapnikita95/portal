"""
Портал - приложение для передачи файлов и синхронизации буфера обмена
через Tailscale сеть с красивым UI в стиле портала
"""

import customtkinter as ctk
import socket
import threading
import json
import os
import shutil
import pyperclip
import time
from pathlib import Path
from typing import Optional, List
import subprocess

# Настройка темы
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class PortalApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("🌀 Портал")
        self.geometry("800x600")
        self.minsize(600, 400)
        
        # Переменные
        self.server_socket: Optional[socket.socket] = None
        self.is_server_running = False
        self.receive_thread: Optional[threading.Thread] = None
        self.clipboard_thread: Optional[threading.Thread] = None
        self.tailscale_ip = self.get_tailscale_ip()
        self.connected_devices = []
        self.sync_clipboard_enabled = False
        self.sync_target_ip = None
        self.is_receiving_clipboard = False
        # IP удалённого ПК для горячих клавиш / виджета (общий буфер и файлы)
        self.remote_peer_ip: Optional[str] = None
        
        # Создание UI
        self.create_ui()
        
        # Запуск мониторинга буфера обмена
        self.start_clipboard_monitor()
        
    def get_tailscale_ip(self) -> Optional[str]:
        """Получает Tailscale IP адрес устройства"""
        # Метод 1: через tailscale status --json
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # Ищем Self в Peer
                self_info = data.get("Self", {})
                tailscale_ips = self_info.get("TailscaleIPs", [])
                for ip in tailscale_ips:
                    if ip.startswith("100."):  # Tailscale IP range
                        return ip
        except:
            pass
        
        # Метод 2: через tailscale ip
        try:
            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                ip = result.stdout.strip()
                if ip and ip.startswith("100."):
                    return ip
        except:
            pass
        
        # Метод 3: через сетевые интерфейсы (Windows)
        try:
            import socket
            # Пробуем подключиться к Tailscale DNS
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("100.100.100.100", 1))
            ip = s.getsockname()[0]
            s.close()
            if ip.startswith("100."):
                return ip
        except:
            pass
        
        # Если Tailscale не найден, возвращаем локальный IP
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return None
    
    def create_ui(self):
        """Создание интерфейса"""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Заголовок
        title_label = ctk.CTkLabel(
            main_frame,
            text="🌀 ПОРТАЛ",
            font=ctk.CTkFont(size=32, weight="bold")
        )
        title_label.pack(pady=(20, 10))
        
        subtitle = ctk.CTkLabel(
            main_frame,
            text="Передача файлов и синхронизация буфера обмена",
            font=ctk.CTkFont(size=14),
            text_color="gray"
        )
        subtitle.pack(pady=(0, 30))
        
        # Информация о подключении
        info_frame = ctk.CTkFrame(main_frame)
        info_frame.pack(fill="x", padx=20, pady=10)
        
        if self.tailscale_ip:
            if self.tailscale_ip.startswith("100."):
                ip_label = ctk.CTkLabel(
                    info_frame,
                    text=f"📍 Tailscale IP: {self.tailscale_ip}",
                    font=ctk.CTkFont(size=12)
                )
                ip_label.pack(pady=10)
            else:
                ip_label = ctk.CTkLabel(
                    info_frame,
                    text=f"📍 Локальный IP: {self.tailscale_ip} (Tailscale не обнаружен)",
                    font=ctk.CTkFont(size=12),
                    text_color="orange"
                )
                ip_label.pack(pady=10)
        else:
            warning_label = ctk.CTkLabel(
                info_frame,
                text="⚠️ IP адрес не определен",
                font=ctk.CTkFont(size=12),
                text_color="orange"
            )
            warning_label.pack(pady=10)
        
        # Кнопки управления
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", padx=20, pady=20)
        
        self.start_button = ctk.CTkButton(
            button_frame,
            text="🚀 Запустить портал",
            command=self.toggle_server,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40
        )
        self.start_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        self.send_button = ctk.CTkButton(
            button_frame,
            text="📤 Отправить файл",
            command=self.send_file_dialog,
            font=ctk.CTkFont(size=14),
            height=40,
            state="disabled"
        )
        self.send_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        self.clipboard_button = ctk.CTkButton(
            button_frame,
            text="📋 Отправить буфер",
            command=self.send_clipboard_dialog,
            font=ctk.CTkFont(size=14),
            height=40,
            state="disabled"
        )
        self.clipboard_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        # Статус
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="⏸ Портал остановлен",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.status_label.pack(pady=10)
        
        # Лог активности
        log_frame = ctk.CTkFrame(main_frame)
        log_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        log_title = ctk.CTkLabel(
            log_frame,
            text="📋 Журнал активности",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        log_title.pack(pady=(10, 5))
        
        self.log_text = ctk.CTkTextbox(log_frame, height=150)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text.insert("1.0", "Готов к работе...\n")
        self.log_text.configure(state="disabled")
    
    def log(self, message: str):
        """Добавление сообщения в лог"""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def toggle_server(self):
        """Запуск/остановка сервера"""
        if not self.is_server_running:
            self.start_server()
        else:
            self.stop_server()
    
    def start_server(self):
        """Запуск сервера для приема файлов"""
        if not self.tailscale_ip:
            self.log("❌ Ошибка: Tailscale IP не найден")
            return
        
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", 12345))
            self.server_socket.listen(5)
            self.is_server_running = True
            
            self.receive_thread = threading.Thread(target=self.server_loop, daemon=True)
            self.receive_thread.start()
            
            self.start_button.configure(text="⏹ Остановить портал")
            self.send_button.configure(state="normal")
            self.clipboard_button.configure(state="normal")
            self.status_label.configure(
                text=f"✅ Портал активен на {self.tailscale_ip}:12345",
                text_color="green"
            )
            self.log(f"✅ Портал запущен на {self.tailscale_ip}:12345")
        except Exception as e:
            self.log(f"❌ Ошибка запуска: {str(e)}")
            self.is_server_running = False
    
    def stop_server(self):
        """Остановка сервера"""
        self.is_server_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        self.start_button.configure(text="🚀 Запустить портал")
        self.send_button.configure(state="disabled")
        self.clipboard_button.configure(state="disabled")
        self.status_label.configure(
            text="⏸ Портал остановлен",
            text_color="gray"
        )
        self.log("⏸ Портал остановлен")
    
    def server_loop(self):
        """Основной цикл сервера"""
        while self.is_server_running:
            try:
                client_socket, addr = self.server_socket.accept()
                self.log(f"🔗 Подключение от {addr[0]}")
                
                # Обработка клиента в отдельном потоке
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, addr),
                    daemon=True
                )
                client_thread.start()
            except:
                if self.is_server_running:
                    self.log("❌ Ошибка приема подключения")
                break
    
    def handle_client(self, client_socket: socket.socket, addr):
        """Обработка клиентского подключения"""
        try:
            # Получение типа операции
            data = client_socket.recv(1024).decode('utf-8')
            message = json.loads(data)
            
            if message.get("type") == "file":
                self.receive_file(client_socket, message)
            elif message.get("type") == "clipboard":
                self.receive_clipboard(message)
            elif message.get("type") == "get_clipboard":
                self.send_clipboard_response(client_socket)
            
        except Exception as e:
            self.log(f"❌ Ошибка обработки клиента: {str(e)}")
        finally:
            client_socket.close()
    
    def receive_file(self, client_socket: socket.socket, message: dict):
        """Прием файла"""
        filename = message.get("filename", "received_file")
        filesize = message.get("filesize", 0)
        
        self.log(f"📥 Прием файла: {filename} ({filesize} байт)")
        
        # Создание папки для приема
        receive_dir = Path.home() / "Desktop" / "Portal_Received"
        receive_dir.mkdir(exist_ok=True)
        
        filepath = receive_dir / filename
        
        # Прием файла
        with open(filepath, "wb") as f:
            remaining = filesize
            while remaining > 0:
                chunk = client_socket.recv(min(8192, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        
        self.log(f"✅ Файл сохранен: {filepath}")
        
        # Подтверждение
        client_socket.send(b"OK")
    
    def receive_clipboard(self, message: dict):
        """Прием буфера обмена"""
        clipboard_text = message.get("text", "")
        if clipboard_text:
            self.is_receiving_clipboard = True
            pyperclip.copy(clipboard_text)
            self.last_clipboard = clipboard_text
            self.is_receiving_clipboard = False
            self.log(f"📋 Буфер обмена обновлен ({len(clipboard_text)} символов)")
    
    def send_clipboard_response(self, client_socket: socket.socket):
        """Отправка текущего локального буфера клиенту (запрос get_clipboard)"""
        try:
            text = pyperclip.paste()
            if text is None:
                text = ""
            resp = json.dumps({"type": "clipboard", "text": text}, ensure_ascii=False)
            client_socket.sendall(resp.encode("utf-8"))
            self.log(f"📋 Отправлен буфер по запросу ({len(text)} символов)")
        except Exception as e:
            self.log(f"❌ Ошибка ответа буфера: {str(e)}")
    
    def set_remote_peer_ip(self, ip: Optional[str]):
        """Сохранить IP второго компьютера для горячих клавиш"""
        self.remote_peer_ip = (ip or "").strip() or None
    
    def push_shared_clipboard_hotkey(self):
        """Ctrl+Alt+C / Cmd+Shift+C — отправить локальный буфер на удалённый ПК"""
        ip = self.remote_peer_ip
        if not ip:
            self.log("⚠️ Сначала укажите IP в виджете (двойной клик по порталу)")
            return
        threading.Thread(target=self.send_clipboard, args=(ip,), daemon=True).start()
    
    def pull_shared_clipboard_hotkey(self):
        """Ctrl+Alt+V / Cmd+Shift+V — забрать буфер с удалённого ПК"""
        ip = self.remote_peer_ip
        if not ip:
            self.log("⚠️ Сначала укажите IP в виджете (двойной клик по порталу)")
            return
        threading.Thread(target=self._pull_clipboard_worker, args=(ip,), daemon=True).start()
    
    def _pull_clipboard_worker(self, target_ip: str):
        """Запрос буфера с удалённой машины (сервер должен быть запущен)"""
        def _log(msg: str):
            try:
                self.after(0, lambda m=msg: self.log(m))
            except Exception:
                print(msg)

        try:
            _log(f"📥 Запрос буфера с {target_ip}...")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(30)
            client_socket.connect((target_ip, 12345))
            client_socket.send(json.dumps({"type": "get_clipboard"}).encode("utf-8"))
            buf = b""
            message = None
            while True:
                part = client_socket.recv(65536)
                if not part:
                    break
                buf += part
                try:
                    message = json.loads(buf.decode("utf-8", errors="replace"))
                    break
                except json.JSONDecodeError:
                    if len(buf) > 4 * 1024 * 1024:
                        break
                    continue
            client_socket.close()
            if message is None:
                raise ValueError("Пустой ответ")
            if message.get("type") == "clipboard":
                text = message.get("text", "")
                self.is_receiving_clipboard = True
                pyperclip.copy(text)
                self.last_clipboard = text
                self.is_receiving_clipboard = False
                _log(f"📋 Буфер с удалённого ПК вставлен ({len(text)} символов)")
            else:
                _log("⚠️ Неожиданный ответ при запросе буфера")
        except Exception as e:
            _log(f"❌ Не удалось получить буфер: {str(e)}")
    
    def send_file_dialog(self):
        """Диалог выбора файла для отправки"""
        from tkinter import filedialog
        filepath = filedialog.askopenfilename(
            title="Выберите файл для отправки"
        )
        if filepath:
            self.send_file_to_dialog(filepath)
    
    def send_file_to_dialog(self, filepath: str):
        """Диалог для ввода IP получателя"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Отправить файл")
        dialog.geometry("400x200")
        
        label = ctk.CTkLabel(
            dialog,
            text="Введите Tailscale IP получателя:",
            font=ctk.CTkFont(size=14)
        )
        label.pack(pady=20)
        
        ip_entry = ctk.CTkEntry(dialog, width=200, font=ctk.CTkFont(size=12))
        ip_entry.pack(pady=10)
        ip_entry.insert(0, "100.")
        
        def send():
            ip = ip_entry.get().strip()
            if ip:
                dialog.destroy()
                threading.Thread(
                    target=self.send_file,
                    args=(filepath, ip),
                    daemon=True
                ).start()
        
        send_button = ctk.CTkButton(
            dialog,
            text="Отправить",
            command=send,
            font=ctk.CTkFont(size=14)
        )
        send_button.pack(pady=20)
    
    def send_clipboard_dialog(self):
        """Диалог для отправки буфера обмена"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Отправить буфер обмена")
        dialog.geometry("400x200")
        
        label = ctk.CTkLabel(
            dialog,
            text="Введите Tailscale IP получателя:",
            font=ctk.CTkFont(size=14)
        )
        label.pack(pady=20)
        
        ip_entry = ctk.CTkEntry(dialog, width=200, font=ctk.CTkFont(size=12))
        ip_entry.pack(pady=10)
        ip_entry.insert(0, "100.")
        
        def send():
            ip = ip_entry.get().strip()
            if ip:
                dialog.destroy()
                threading.Thread(
                    target=self.send_clipboard,
                    args=(ip,),
                    daemon=True
                ).start()
        
        send_button = ctk.CTkButton(
            dialog,
            text="Отправить",
            command=send,
            font=ctk.CTkFont(size=14)
        )
        send_button.pack(pady=20)
    
    def send_file(self, filepath: str, target_ip: str):
        """Отправка файла"""
        try:
            self.log(f"📤 Отправка файла на {target_ip}...")
            
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((target_ip, 12345))
            
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)
            
            # Отправка метаданных
            message = {
                "type": "file",
                "filename": filename,
                "filesize": filesize
            }
            client_socket.send(json.dumps(message).encode('utf-8'))
            time.sleep(0.1)  # Небольшая задержка
            
            # Отправка файла
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    client_socket.send(chunk)
            
            # Ожидание подтверждения
            response = client_socket.recv(1024)
            client_socket.close()
            
            if response == b"OK":
                self.log(f"✅ Файл успешно отправлен: {filename}")
            else:
                self.log(f"⚠️ Неопределенный ответ от получателя")
                
        except Exception as e:
            self.log(f"❌ Ошибка отправки: {str(e)}")
    
    def send_clipboard(self, target_ip: str):
        """Отправка буфера обмена"""
        try:
            clipboard_text = pyperclip.paste()
            if not clipboard_text:
                self.log("⚠️ Буфер обмена пуст")
                return
            
            self.log(f"📤 Отправка буфера обмена на {target_ip}...")
            
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((target_ip, 12345))
            
            # Отправка метаданных
            message = {
                "type": "clipboard",
                "text": clipboard_text
            }
            client_socket.send(json.dumps(message).encode('utf-8'))
            client_socket.close()
            
            self.log(f"✅ Буфер обмена отправлен ({len(clipboard_text)} символов)")
                
        except Exception as e:
            self.log(f"❌ Ошибка отправки буфера: {str(e)}")
    
    def start_clipboard_monitor(self):
        """Запуск мониторинга буфера обмена"""
        self.last_clipboard = pyperclip.paste()
        self.clipboard_thread = threading.Thread(
            target=self.clipboard_monitor_loop,
            daemon=True
        )
        self.clipboard_thread.start()
    
    def clipboard_monitor_loop(self):
        """Цикл мониторинга буфера обмена"""
        while True:
            try:
                if not self.is_receiving_clipboard:
                    current = pyperclip.paste()
                    if current != self.last_clipboard:
                        self.last_clipboard = current
                        # Автоматическая синхронизация (если включена)
                        if self.sync_clipboard_enabled and self.sync_target_ip:
                            threading.Thread(
                                target=self.send_clipboard,
                                args=(self.sync_target_ip,),
                                daemon=True
                            ).start()
            except:
                pass
            time.sleep(0.5)


if __name__ == "__main__":
    import sys
    
    # Проверяем аргументы командной строки
    show_widget = "--widget" in sys.argv or "-w" in sys.argv
    
    app = PortalApp()
    
    # Если запрошен виджет, создаем его
    if show_widget:
        try:
            from portal_widget import PortalWidget, GlobalHotkeyManager
            widget = PortalWidget(app)
            GlobalHotkeyManager(widget, app).start()
            app.log("✅ Виджет-портал создан (Alt+ЛКМ — двигать окно, Ctrl+ЛКМ — файл)")
        except Exception as e:
            app.log(f"⚠️ Не удалось создать виджет: {str(e)}")
    
    app.mainloop()
