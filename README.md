# Robot Camera Scanner

Консольный сканер камер для робота. Он одновременно обнаруживает:

- Intel RealSense;
- Luxonis OAK, включая OAK-D-W.

Для каждой камеры выводятся название и серийный номер. Для OAK серийным
номером считается уникальный DeviceID/MX ID. Для RealSense дополнительно
определяется логическое расположение по USB-порту хаба.

## Поддерживаемые системы

- macOS;
- Ubuntu 20.04, 22.04 и 24.04 LTS;
- другие Debian-подобные системы могут работать, но автоматическая установка
  RealSense официально проверялась только на поддерживаемых версиях Ubuntu.

Windows сейчас не поддерживается, потому что основной сканер написан на Bash.

## Быстрый старт

Склонируйте репозиторий и перейдите в его каталог:

```bash
git clone https://github.com/YOUR_USERNAME/robot-camera-scanner.git
cd robot-camera-scanner
```

Запустите установщик:

```bash
chmod +x setup.sh camera-scan
./setup.sh
```

Установщик проверит окружение и предложит установить только недостающие
компоненты. Для полностью автоматического запуска без вопроса подтверждения:

```bash
./setup.sh --yes
```

После установки подключите камеры и выполните:

```bash
./camera-scan
```

На macOS сканер может запросить пароль администратора. Пароль вводится самим
пользователем в системный `sudo`; скрипт его не сохраняет.

## Что устанавливает setup.sh

На macOS:

- Homebrew, если он отсутствует;
- Python 3, если он отсутствует;
- `librealsense` с утилитой `rs-enumerate-devices`;
- локальное Python-окружение `.venv`;
- пакет `depthai` из `requirements.txt`.

На Ubuntu/Debian:

- Python 3, `venv`, `curl`, GnuPG и служебные пакеты APT;
- официальный репозиторий RealSense;
- `librealsense2-utils` и `librealsense2-dkms`;
- udev-правило для USB-камер OAK;
- локальное Python-окружение `.venv`;
- пакет `depthai`.

`.venv` находится внутри проекта и не добавляется в Git. Сканер использует
Python из этого окружения по абсолютному пути, поэтому DepthAI остаётся
доступен и после запуска через `sudo`.

## Проверка зависимостей

Проверить окружение без сканирования камер:

```bash
./camera-scan --check-dependencies
```

Ожидаемый результат:

```text
Dependency check
================
[OK] RealSense SDK: /opt/homebrew/bin/rs-enumerate-devices
[OK] Python: Python 3.x.x
[OK] DepthAI: 3.x.x

All required dependencies are installed.
```

## Пример результата

```text
==========================================
        Robot Camera Scanner
==========================================

Cameras found: 2

1. Intel RealSense D435
   Serial number: 123456789
   Location: Hub Port 4 — Left Hand

2. OAK-D-W
   Serial number: 18443010ABCDEF0000
   USB path: 1.2.3

==========================================
```

## Ручная установка на macOS

Если автоматический установщик не подходит:

```bash
brew install python librealsense
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
chmod +x camera-scan
```

Проверка:

```bash
rs-enumerate-devices --version
.venv/bin/python3 -c "import depthai; print(depthai.__version__)"
./camera-scan --check-dependencies
```

## Ручная установка на Ubuntu

Для RealSense используйте официальную инструкцию:

<https://github.com/realsenseai/librealsense/blob/master/doc/distribution_linux.md>

Для OAK установите USB-правило:

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Затем установите DepthAI локально:

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
chmod +x camera-scan
```

Официальная инструкция Luxonis:

<https://docs.luxonis.com/hardware/platform/deploy/usb-deployment-guide/>

## Troubleshooting

### Ни одна камера не найдена

1. Отсоедините и снова подключите камеру.
2. Используйте USB-кабель с передачей данных, а не кабель только для зарядки.
3. Подключите камеру напрямую к USB 3 порту без пассивного хаба.
4. Закройте RealSense Viewer, OAK Viewer и другие процессы, использующие камеру.
5. Повторите `./setup.sh`, затем `./camera-scan --check-dependencies`.

### RealSense не обнаруживается

Проверьте саму утилиту:

```bash
rs-enumerate-devices
```

На macOS попробуйте:

```bash
sudo rs-enumerate-devices
```

Если команда отсутствует, повторите `./setup.sh`. На Ubuntu после установки
DKMS переподключите камеру; иногда требуется перезагрузка.

Проверить наличие USB-устройства в Linux:

```bash
lsusb | grep -i -E 'realsense|8086'
```

### OAK-D-W не обнаруживается

Проверьте пакет и список устройств:

```bash
.venv/bin/python3 -c \
  "import depthai as dai; print(dai.__version__, dai.Device.getAllAvailableDevices())"
```

На Linux сообщение `Insufficient permissions` означает, что не применилось
udev-правило. Повторите `./setup.sh`, переподключите камеру и проверьте:

```bash
lsusb | grep 03e7
```

Для OAK рекомендуется короткий качественный USB 3 кабель. При нестабильном
питании используйте активный USB-хаб или внешнее питание камеры.

### OAK показана как “Luxonis OAK camera”

Серийный номер при этом корректен. Общее имя означает, что устройство найдено,
но EEPROM нельзя было прочитать — чаще всего камера уже занята другим
приложением. Закройте OAK Viewer или другой процесс и повторите сканирование.

### DepthAI установлен, но сканер его не видит

Не устанавливайте пакет через случайный системный `pip`. Повторите:

```bash
./setup.sh
./camera-scan --check-dependencies
```

Сканер намеренно использует `.venv/bin/python3` из каталога проекта.

### Ошибка сети, pip или APT

Убедитесь, что доступны:

- `https://pypi.org`;
- `https://librealsense.realsenseai.com`;
- `https://github.com`.

В корпоративной сети может потребоваться настройка HTTP/HTTPS-прокси и
сертификата организации.

### Secure Boot мешает установить RealSense DKMS

Ubuntu с включённым Secure Boot может отклонить сторонний модуль ядра. Следуйте
диалогу MOK при установке пакета либо используйте рекомендации производителя
компьютера. После изменения настроек перезагрузите систему.

## Диагностическая информация для issue

Приложите к issue вывод этих команд:

```bash
uname -a
./camera-scan --check-dependencies
rs-enumerate-devices
.venv/bin/python3 -c \
  "import depthai as dai; print(dai.__version__, dai.Device.getAllAvailableDevices())"
```

На Linux также:

```bash
lsusb
```

Не публикуйте лишние персональные данные из системного вывода.

## Структура проекта

```text
robot-camera-scanner/
├── camera-scan       # основной сканер
├── setup.sh          # автоматическая установка и проверка
├── requirements.txt  # Python-зависимости
├── README.md
└── .gitignore
```

## Публикация на GitHub

Перед публикацией замените `YOUR_USERNAME` в команде клонирования выше на имя
вашего GitHub-аккаунта. Затем:

```bash
git init
git add .
git commit -m "Initial camera scanner release"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/robot-camera-scanner.git
git push -u origin main
```

Перед открытой публикацией выберите лицензию проекта и добавьте файл `LICENSE`.
