# Сборка APK на Mac/Windows через Docker (Linux-образ).
# Из каталога portal-android:
#   docker build -t portal-buildozer .
#   docker run --rm -v "$PWD":/home/user/host -u $(id -u):$(id -g) portal-buildozer
#
# APK появится в ./bin/*.apk (кэш .buildozer сохраняй volume при необходимости).
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    git zip unzip openjdk-17-jdk python3-pip wget \
    autoconf automake libtool pkg-config zlib1g-dev \
    libncurses5-dev libncursesw5-dev cmake libffi-dev libssl-dev \
    libltdl-dev \
  && rm -rf /var/lib/apt/lists/*
# Cython 3 ломает сборку PyJNIUS (long в .pxi) — держим 0.29.x как в CI
RUN pip3 install --no-cache-dir "cython>=0.29.36,<3.0" buildozer
WORKDIR /home/user/host
# По умолчанию — полная сборка (долго при первом запуске).
CMD ["buildozer", "android", "debug"]
