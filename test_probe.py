#!/usr/bin/env python3
"""
Ручная проверка ping→pong к Портал-серверу.
Запуск: python test_probe.py 100.65.63.84
Или: python test_probe.py 100.65.63.84 12345
"""
import sys
import json
import socket

try:
    from portal import merge_outgoing_shared_secret
except ImportError:
    merge_outgoing_shared_secret = None  # type: ignore

PORT = 12345
TIMEOUT = 10.0


def main():
    if len(sys.argv) < 2:
        print("Использование: python test_probe.py <IP> [порт]")
        print("Пример: python test_probe.py 100.65.63.84")
        sys.exit(1)

    host = sys.argv[1].strip()
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Проверка {host}:{port} (timeout {TIMEOUT}s)")
    print("-" * 50)

    s = None
    tcp_ok = False
    try:
        print("1. Создаю сокет…")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)

        print("2. Подключаюсь…")
        s.connect((host, port))
        tcp_ok = True
        print("   TCP connect OK")

        print("3. Шлю ping…")
        ping = {"type": "ping"}
        if merge_outgoing_shared_secret is not None:
            ping = merge_outgoing_shared_secret(ping)
        s.sendall(json.dumps(ping, ensure_ascii=False).encode("utf-8"))

        print("4. Жду pong (5s)…")
        s.settimeout(5.0)
        data = s.recv(4096)
        if not data:
            print("   Пусто (соединение закрыто без данных)")
            sys.exit(2)

        print(f"   Получено {len(data)} байт: {data[:80]!r}…")
        msg = json.loads(data.decode("utf-8"))
        if msg.get("type") == "pong":
            print("   pong OK!")
            sys.exit(0)
        print(f"   Ответ не pong: {msg}")
        sys.exit(3)

    except ConnectionRefusedError:
        print("2. Connection refused — порт закрыт или не слушает")
        sys.exit(4)
    except socket.timeout:
        if tcp_ok:
            print("4. Таймаут на recv — TCP есть, pong не пришёл (старая версия на паре)")
        else:
            print("2. Таймаут — нет маршрута до хоста (connect не прошёл)")
        sys.exit(5)
    except socket.gaierror as e:
        print(f"2. DNS ошибка: {e}")
        sys.exit(6)
    except Exception as e:
        print(f"Ошибка: {type(e).__name__}: {e}")
        sys.exit(7)
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
