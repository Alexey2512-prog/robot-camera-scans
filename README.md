# Robot Camera Scanner

Консольный сканер камер для робота. Он одновременно обнаруживает:

- Intel RealSense;
- Luxonis OAK, включая OAK-D-W.

Для каждой камеры выводятся название и серийный номер. Для OAK серийным
номером считается уникальный DeviceID/MX ID. Для RealSense дополнительно
определяется логическое расположение по USB-порту хаба. Сканер также показывает
согласованный режим USB, результат проверки стабильности, фактический FPS и
потери кадров в коротком видеопотоке. Дополнительно рассчитываются jitter,
интервалы между кадрами и итоговый статус здоровья камеры.

## Поддерживаемые системы

- macOS;
- Ubuntu 20.04, 22.04 и 24.04 LTS;
- другие Debian-подобные системы могут работать, но автоматическая установка
  RealSense официально проверялась только на поддерживаемых версиях Ubuntu.

Windows сейчас не поддерживается, потому что основной сканер написан на Bash.

## Быстрый старт

Склонируйте репозиторий и перейдите в его каталог:

```bash
git clone https://github.com/Alexey2512-prog/robot-camera-scans.git
cd robot-camera-scans
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

Параллельный стресс-тест всех камер на общей USB-шине:

```bash
./camera-scan --parallel --duration 10 --samples 10
```

Сохранить машиночитаемый отчёт:

```bash
./camera-scan --parallel --output reports/cameras.json
./camera-scan --json
```

На macOS сканер может запросить пароль администратора. Пароль вводится самим
пользователем в системный `sudo`; скрипт его не сохраняет.

## Основные параметры

```text
--duration SECONDS       длительность потокового теста, 0–30 секунд
--samples COUNT          число проверок стабильности, 1–20
--parallel               тестировать все камеры одновременно
--camera all|realsense|oak
                         ограничить проверку одним семейством
--json                   вывести JSON вместо текста
--output FILE            сохранить JSON-отчёт в файл
--check-dependencies     проверить окружение без обращения к камерам
```

Полная справка:

```bash
./camera-scan --help
```

## Что устанавливает setup.sh

На macOS:

- Homebrew, если он отсутствует;
- Python 3, если он отсутствует;
- `librealsense` с утилитой `rs-enumerate-devices`;
- консольный помощник для теста FPS RealSense, собранный из исходного кода;
- локальное Python-окружение `.venv`;
- пакет `depthai` из `requirements.txt`.

На Ubuntu/Debian:

- Python 3, `venv`, `curl`, GnuPG и служебные пакеты APT;
- официальный репозиторий RealSense;
- `librealsense2-utils`, `librealsense2-dkms` и `librealsense2-dev`;
- компилятор C++ и консольный помощник для теста FPS RealSense;
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
[OK] DepthAI: 3.x.x
[OK] RealSense FPS/frame-loss helper

All required dependencies are installed.
```

## Пример результата

```text
==========================================
        Robot Camera Scanner
==========================================

Overall status: WARNING
Frame-test mode: parallel
Cameras found: 2

1. Intel RealSense D435
   Type: realsense
   Serial number: 123456789
   Health: OK
   Connection speed: USB 3.2 (SuperSpeed)
   Stability: Stable (5/5 checks)
   Frame test: 29.9 FPS (target 30); 90 frames; 0 dropped (0.0%)
   Timing: interval p95 34.1 ms; jitter p95 1.2 ms; max gap 35.0 ms
   Max consecutive drops: 0
   Location: Hub Port 4 — Left Hand

2. OAK-D-W
   Type: oak
   Serial number: 18443010ABCDEF0000
   Health: WARNING
   Connection speed: USB 3.x SuperSpeed (5 Gbit/s)
   Stability: Stable (5/5 checks)
   Frame test: 29.8 FPS (target 30); 89 frames; 1 dropped (1.1%)
   Timing: interval p95 35.2 ms; jitter p95 1.7 ms; max gap 67.0 ms
   Max consecutive drops: 1
   USB path: 1.2.3
   - frame loss is 1.1%

==========================================
```

## Скорость и стабильность подключения

`Connection speed` — согласованный USB-режим, который сообщает драйвер камеры.
Это предельная скорость интерфейса, а не измеренная скорость передачи кадров.
Например, `USB 2.0 High-Speed (480 Mbit/s)` означает, что OAK подключилась в
режиме USB 2.0; для нормальной работы стереокамеры предпочтителен USB 3.

`Stability` — результат пяти обнаружений камеры с короткими паузами:

- `Stable (5/5 checks)` — камера была доступна во всех проверках;
- `Unstable (3/5 checks)` — камера временно пропадала;
- `Not checked` — проверка невозможна, например нет серийного номера.

Количество проверок можно изменить от 1 до 20:

```bash
./camera-scan --samples 10
```

Эта быстрая проверка подтверждает стабильность обнаружения USB-устройства. Она
не заменяет длительный тест видеопотока, FPS, потерь кадров или пропускной
способности под нагрузкой.

Для OAK скорость читается через официальный метод DepthAI `getUsbSpeed()`:

<https://docs.luxonis.com/software-v3/depthai/depthai-components/device>

## FPS и потери кадров

По умолчанию сканер запускает для каждой камеры трёхсекундный потоковый тест:

- RealSense — поток глубины с профилем, выбранным librealsense;
- OAK-D-W — поток `CAM_A` размером 640×400 с целевыми 30 FPS.

Пример:

```text
Frame test: 29.9 FPS (target 30); 90 frames; 2 dropped (2.2%)
```

Фактический FPS вычисляется по времени прихода кадров. Потери определяются по
разрывам в sequence number, который выдаёт камера. Также выводятся:

- `interval p95` — 95-й перцентиль интервала между кадрами;
- `jitter p95` — 95-й перцентиль отклонения интервала от медианы;
- `max gap` — самый длинный промежуток без нового кадра;
- `Max consecutive drops` — максимальная серия потерянных кадров;
- `Host latency p95` — оценка задержки OAK, если timestamp доступен.

По умолчанию камеры тестируются последовательно. Флаг `--parallel` запускает
их одновременно и выявляет нехватку полосы общего USB-контроллера.

Изменить длительность теста можно в диапазоне от 1 до 30 секунд:

```bash
./camera-scan --duration 10
```

Отключить потоковый тест и оставить только обнаружение камер:

```bash
./camera-scan --duration 0
```

Короткий тест помогает быстро найти проблемы, но не гарантирует отсутствие
редких потерь. Для диагностики плавающей неисправности используйте 10–30 секунд.

## Статусы здоровья и коды завершения

Каждая камера и весь запуск получают статус:

- `OK` — проверки прошли без замечаний;
- `WARNING` — потери ≥0,5%, FPS ниже 95% цели, jitter p95 ≥5 мс,
  неполная стабильность или USB 2.0;
- `FAILED` — потери ≥5%, FPS ниже 80% цели, jitter p95 ≥15 мс,
  поток не открылся либо камера часто пропадает.

Коды завершения подходят для CI, systemd и ROS-скриптов:

- `0` — `OK`;
- `1` — `WARNING`;
- `2` — `FAILED`, камеры не найдены или отсутствуют зависимости.

## JSON-отчёт

Вывести только JSON в stdout:

```bash
./camera-scan --parallel --duration 10 --json
```

Сохранить JSON и оставить обычный текст в терминале:

```bash
./camera-scan --parallel --output reports/cameras.json
```

Отчёт содержит конфигурацию запуска, общий статус, метрики каждой камеры,
причины `WARNING`/`FAILED` и версию схемы. Каталог `reports/` исключён из Git.

## Ручная установка на macOS

Если автоматический установщик не подходит:

```bash
brew install python librealsense
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
mkdir -p .build
LIBREALSENSE_PREFIX="$(brew --prefix librealsense)"
c++ -std=c++17 -O2 tools/rs-frame-test.cpp \
  -I"$LIBREALSENSE_PREFIX/include" \
  -L"$LIBREALSENSE_PREFIX/lib" \
  -Wl,-rpath,"$LIBREALSENSE_PREFIX/lib" \
  -lrealsense2 -o .build/rs-frame-test
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

Для ручной сборки теста FPS установите пакеты разработчика и скомпилируйте
помощник:

```bash
sudo apt-get install build-essential pkg-config librealsense2-dev
mkdir -p .build
c++ -std=c++17 -O2 $(pkg-config --cflags realsense2) \
  tools/rs-frame-test.cpp $(pkg-config --libs realsense2) \
  -o .build/rs-frame-test
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

### Stability показывает Unstable

1. Подключите камеру напрямую, исключив пассивный USB-хаб.
2. Замените кабель на короткий USB 3 кабель с передачей данных.
3. Закройте приложения, которые могут перезапускать или занимать камеру.
4. Для OAK проверьте достаточность питания; при необходимости используйте
   активный хаб или внешнее питание.
5. Запустите расширенную проверку:

```bash
./camera-scan --samples 10
```

Если `Connection speed` показывает USB 2.0 вместо USB 3, чаще всего причина в
кабеле, хабе, переходнике или выбранном порте компьютера.

### Frame test показывает dropped frames или низкий FPS

1. Закройте RealSense Viewer, OAK Viewer, ROS-ноды и другие процессы камеры.
2. Подключите камеру напрямую к USB 3 порту.
3. Замените кабель и исключите переходники или пассивный хаб.
4. Проверьте питание OAK-D-W.
5. Повторите десятисекундный тест:

```bash
./camera-scan --duration 10
```

Небольшое отклонение, например 29.8 вместо 30 FPS, нормально для измерения по
часам компьютера. Разрывы sequence number отображаются отдельно как `dropped`.

### Frame test показывает Failed или Not tested

Сначала пересоберите помощник и проверьте зависимости:

```bash
./setup.sh
./camera-scan --check-dependencies
```

Если ошибка сохраняется, закройте использующие камеру приложения и повторно
подключите устройство. DepthAI 2 продолжает поддерживаться для обнаружения OAK,
но потоковый FPS-тест OAK требует DepthAI 3.

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
robot-camera-scans/
├── camera-scan       # Bash launcher и sudo для macOS
├── scanner.py        # обнаружение, метрики, JSON и статусы
├── setup.sh          # автоматическая установка и проверка
├── requirements.txt  # Python-зависимости
├── tools/
│   └── rs-frame-test.cpp  # потоковый тест RealSense
├── tests/
│   └── test_scanner.py    # unit-тесты парсеров, метрик и статусов
├── .github/workflows/
│   └── ci.yml             # CI на Ubuntu и macOS
├── README.md
└── .gitignore
```

## Разработка

Запустить unit-тесты локально:

```bash
python3 -m unittest discover -s tests -v
```

GitHub Actions выполняет Bash-проверки и Python unit-тесты на Ubuntu и macOS.
