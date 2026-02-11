# Transcribe Bot

Telegram-бот для транскрибации аудио/видеозаписей и автоматического анализа с планом развития.

Бот принимает аудио- или видеофайл, транскрибирует речь через **Yandex SpeechKit**, анализирует текст через **YandexGPT Pro** и отдает структурированный результат с возможностью выгрузки в PDF.

## Возможности

- Транскрибация аудио (OGG, MP3, WAV, FLAC, M4A) и видео (MP4, AVI, MOV, MKV, WEBM)
- Автоматическое извлечение аудиодорожки из видео (FFmpeg)
- Разделение больших файлов (>4 часов / >1 ГБ) на части
- Анализ текста через YandexGPT Pro: резюме, ключевые тезисы, план развития
- Экспорт результатов в PDF
- История транскрибаций
- Параллельная обработка файлов (очередь с 3 воркерами)
- Авторизация по паролю, лимит 20 пользователей

---

## Архитектура

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  Telegram    │────▶│  Yandex Cloud    │────▶│  Yandex Object       │
│  User        │     │  Compute (VM)    │     │  Storage (S3)        │
└─────────────┘     │  Docker          │     └──────────┬───────────┘
                    └──────┬───────────┘                │
                           │                            │
                    ┌──────▼───────────┐     ┌──────────▼───────────┐
                    │  PostgreSQL      │     │  Yandex SpeechKit    │
                    │  (Docker/Managed)│     │  (STT API)           │
                    └──────────────────┘     └──────────────────────┘
                                                        │
                                             ┌──────────▼───────────┐
                                             │  YandexGPT Pro       │
                                             │  (Analysis API)      │
                                             └──────────────────────┘
```

### Стек технологий

| Компонент | Технология |
|---|---|
| Язык | Python 3.12 |
| Telegram Bot | python-telegram-bot v22 (async) |
| HTTP-клиент | httpx |
| Object Storage | boto3 (S3 API) |
| Обработка аудио | FFmpeg |
| База данных | PostgreSQL 16 + SQLAlchemy async |
| Генерация PDF | ReportLab |
| Контейнеризация | Docker + Docker Compose |
| Зависимости | uv |

---

## Ответы на вопросы команды

### 1. Извлечение звуковой дорожки из видео

**Реализовано.** Бот автоматически определяет тип файла (аудио/видео) и при получении видео (MP4, AVI, MOV, MKV, WEBM) извлекает аудиодорожку через FFmpeg с конвертацией в OGG OPUS 48 кГц моно — именно этот формат оптимален для Yandex SpeechKit.

### 2. Асинхронное распознавание и разделение файлов

**Реализовано.** Используется API SpeechKit v2 (`/speech/stt/v2/longRunningRecognize`) — отложенный (deferred) режим асинхронного распознавания. Бот отправляет запрос на распознавание, получает ID операции и периодически опрашивает статус (каждые 5 секунд, таймаут 30 минут) до получения результата.

Файлы автоматически разделяются при достижении ограничений:
- **По длительности**: > 4 часов (14 400 секунд)
- **По размеру**: > 1 ГБ (1 073 741 824 байт)

Разделение выполняется через FFmpeg с помощью segment feature. Каждая часть распознаётся отдельно, результаты конкатенируются в единый текст.

### 3. Стоимость распознавания

Используется **отложенный режим** (самый дешёвый):

| Сервис Yandex AI Studio | Тариф | 30 мин | 1 час | 4 часа |
|---|---|---|---|---|
| **SpeechKit — Отложенный режим** (используется в боте) | **0,002542 ₽/сек** | **~4,58 ₽** | ~9,15 ₽ | ~36,60 ₽ |
| SpeechKit — Асинхронное распознавание | 0,0102 ₽/сек | ~18,36 ₽ | ~36,72 ₽ | ~146,88 ₽ |
| SpeechKit — Разметка аудио (diarization) | 38,63 ₽/unit | — | — | — |

> **Почему отложенный режим?** В 4 раза дешевле асинхронного. Время обработки немного дольше, но для задачи транскрибации записей (не в реальном времени) это оптимальный выбор.

> **Разметка аудио (diarization)** — определение «кто говорит». Стоит 38,63 ₽ за единицу разметки. Запланирована в v2, когда появится потребность в протоколировании совещаний с указанием спикеров.

### 4. Расходы на сервер приложений и БД

| Ресурс | Вариант | Стоимость |
|---|---|---|
| **Compute VM** | standard-v3, 2 ядра, 2 ГБ RAM, 20% CPU, 15 ГБ SSD | **~800-1 500 ₽/мес** |
| **PostgreSQL** (вариант A) | Docker на VM (рядом с ботом) | **0 ₽** (включено в VM) |
| **PostgreSQL** (вариант B) | Managed PostgreSQL s2.micro | ~1 000-2 000 ₽/мес |
| **Object Storage** | Хранение аудио (временное, удаляется после обработки) | **~2 ₽/ГБ** (пренебрежимо мало) |
| **YandexGPT Pro** | Анализ текста транскрибации | **~1-3 ₽** за запрос |

**Текущий деплой использует Docker PostgreSQL на VM** — минимальные расходы.

#### Итого: стоимость обработки одного 30-минутного интервью

| Статья | Сумма |
|---|---|
| SpeechKit (отложенный) | ~4,58 ₽ |
| YandexGPT Pro (анализ) | ~2,00 ₽ |
| Object Storage (временно) | ~0,01 ₽ |
| **Итого за файл** | **~6-7 ₽** |
| Инфраструктура (VM) | ~800-1 500 ₽/мес (фиксировано) |

### Другие вопросы команды

| Вопрос | Ответ |
|---|---|
| Какой мессенджер? | **Telegram-бот** (v1). Яндекс.Мессенджер — в будущих версиях. |
| Какой интерфейс? | Telegram: отправка файлов + inline-кнопки (PDF, история). |
| Подписка? | Нет подписки. Доступ по паролю (`changeme`), лимит 20 пользователей. |
| Можно ли ТГ или Яндекс.Мессенджер? | Telegram (v1). Один бэкенд, мессенджеры и ViWork — позже. |
| Какой промпт и настройка? | Единый универсальный промпт YandexGPT Pro (резюме + ключевые тезисы + план развития). Без адаптации под тип контента (v1). |
| Какой ИИ для рекомендаций? | **YandexGPT Pro** — экосистема Yandex Cloud, лучший для русского языка. |
| Привязка к ViWork? | Отдельный сервис с единым бэкендом API. Не в v1. |

---

## Быстрый старт (локальная разработка)

### Предварительные требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — менеджер пакетов
- Docker и Docker Compose
- Аккаунт Yandex Cloud с настроенными сервисами

### Установка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd transcribe

# Установить зависимости
uv sync --all-extras

# Скопировать и заполнить .env
cp .env.example .env
# Отредактировать .env — заполнить реальные значения

# Запустить PostgreSQL в Docker
docker compose up db -d

# Запустить бота
uv run python -m src.main
```

### Запуск через Docker Compose (полный стек)

```bash
# Заполнить .env
cp .env.example .env

# Положить ключ сервисного аккаунта
# Раскомментировать volume в docker-compose.yml

# Собрать и запустить
docker compose up --build -d

# Проверить логи
docker compose logs -f bot
```

---

## Подробная инструкция развертывания на Yandex Cloud

### Шаг 1: Создание облака и каталога

1. Зарегистрируйтесь на [console.yandex.cloud](https://console.yandex.cloud)
2. Создайте облако (или используйте существующее)
3. Создайте каталог (folder), например `transcribe-bot`
4. Запомните **ID каталога** — понадобится для `YC_FOLDER_ID`

### Шаг 2: Установка Yandex Cloud CLI

```bash
curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash
yc init
```

### Шаг 3: Создание сервисного аккаунта

```bash
# Создать сервисный аккаунт
yc iam service-account create --name transcribe-bot-sa

# Получить ID сервисного аккаунта
SA_ID=$(yc iam service-account get transcribe-bot-sa --format json | jq -r '.id')

# Назначить роли
yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role storage.editor \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role ai.speechkit-stt.user \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role ai.languageModels.user \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role iam.serviceAccounts.tokenCreator \
  --subject serviceAccount:$SA_ID
```

### Шаг 4: Создание ключей доступа

```bash
# Авторизованный ключ для IAM-токенов (JSON)
yc iam key create --service-account-name transcribe-bot-sa \
  --output sa-key.json

# Статические ключи для Object Storage
yc iam access-key create --service-account-name transcribe-bot-sa
# Запишите access_key.id → YC_S3_ACCESS_KEY
# Запишите secret → YC_S3_SECRET_KEY
```

### Шаг 5: Создание бакета Object Storage

```bash
# Через консоль: https://console.yandex.cloud/folders/<FOLDER_ID>/storage
# Или через CLI:
yc storage bucket create --name transcribe-bot-audio
```

### Шаг 6: База данных PostgreSQL

**Вариант A: Managed PostgreSQL (рекомендуется для продакшена)**

```bash
yc managed-postgresql cluster create \
  --name transcribe-db \
  --environment production \
  --network-name default \
  --resource-preset s2.micro \
  --disk-type network-ssd \
  --disk-size 10 \
  --host zone-id=ru-central1-a,subnet-name=default-ru-central1-a \
  --database name=transcribe_bot \
  --user name=transcribe,password=<STRONG_PASSWORD>
```

**Вариант B: PostgreSQL в Docker на VM (бюджетный вариант)**

PostgreSQL включён в `docker-compose.yml` — запускается автоматически.

### Шаг 7: Создание VM (Compute Cloud)

```bash
yc compute instance create \
  --name transcribe-bot-vm \
  --zone ru-central1-a \
  --platform standard-v2 \
  --cores 2 \
  --memory 2 \
  --core-fraction 20 \
  --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2204-lts,size=15 \
  --network-interface subnet-name=default-ru-central1-a,nat-ip-version=ipv4 \
  --ssh-key ~/.ssh/id_rsa.pub
```

Запомните внешний IP-адрес VM.

### Шаг 8: Настройка VM

```bash
# Подключиться по SSH
ssh yc-user@<VM_IP>

# Установить Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Установить Docker Compose
sudo apt-get install -y docker-compose-plugin

# Перелогиниться для применения группы docker
exit
ssh yc-user@<VM_IP>
```

### Шаг 9: Деплой приложения

```bash
# Клонировать репозиторий
git clone <repo-url> ~/transcribe
cd ~/transcribe

# Скопировать ключ сервисного аккаунта на VM
# (с локальной машины)
scp sa-key.json yc-user@<VM_IP>:~/transcribe/sa-key.json

# Создать .env файл
cp .env.example .env
nano .env
# Заполнить все значения:
# TELEGRAM_BOT_TOKEN=<от @BotFather>
# YC_FOLDER_ID=<ID каталога>
# YC_SERVICE_ACCOUNT_KEY_FILE=/app/sa-key.json
# YC_S3_ACCESS_KEY=<из шага 4>
# YC_S3_SECRET_KEY=<из шага 4>
# DATABASE_URL=postgresql+asyncpg://transcribe:transcribe@db:5432/transcribe_bot

# Раскомментировать volume для sa-key.json в docker-compose.yml
```

### Шаг 10: Запуск

```bash
# Собрать и запустить
docker compose up --build -d

# Проверить логи
docker compose logs -f bot

# Проверить статус
docker compose ps
```

### Шаг 11: Регистрация Telegram-бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Укажите имя бота (например, `Transcribe Bot`)
4. Укажите username (например, `my_transcribe_bot`)
5. Скопируйте полученный токен в `.env` → `TELEGRAM_BOT_TOKEN`
6. Перезапустите бота: `docker compose restart bot`

### Шаг 12: Проверка

1. Найдите бота в Telegram по username
2. Отправьте `/start`
3. Введите пароль: `changeme`
4. Отправьте тестовый аудиофайл
5. Дождитесь транскрибации и анализа

---

## Переменные окружения

| Переменная | Обязательная | Описание | Пример |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Да | Токен Telegram-бота от @BotFather | `123456:ABC-DEF` |
| `BOT_ACCESS_PASSWORD` | Нет | Пароль для доступа (по умолчанию `changeme`) | `changeme` |
| `MAX_USERS` | Нет | Макс. авторизованных пользователей (по умолчанию `20`) | `20` |
| `YC_FOLDER_ID` | Да | ID каталога Yandex Cloud | `b1g0000000000` |
| `YC_SERVICE_ACCOUNT_KEY_FILE` | Да | Путь к JSON-ключу сервисного аккаунта | `/app/sa-key.json` |
| `YC_S3_BUCKET` | Нет | Имя бакета Object Storage (по умолчанию `transcribe-bot-audio`) | `transcribe-bot-audio` |
| `YC_S3_ACCESS_KEY` | Да | Access Key для Object Storage | `YCAJ...` |
| `YC_S3_SECRET_KEY` | Да | Secret Key для Object Storage | `YCP...` |
| `YC_S3_ENDPOINT` | Нет | Эндпоинт S3 | `https://storage.yandexcloud.net` |
| `SPEECHKIT_API_ENDPOINT` | Нет | Эндпоинт SpeechKit | `https://transcribe.api.cloud.yandex.net` |
| `YANDEXGPT_API_ENDPOINT` | Нет | Эндпоинт YandexGPT | `https://llm.api.cloud.yandex.net` |
| `YANDEXGPT_MODEL_URI` | Нет | URI модели (авто-генерируется из FOLDER_ID) | `gpt://folder/yandexgpt/latest` |
| `DATABASE_URL` | Да | Строка подключения к PostgreSQL | `postgresql+asyncpg://user:pass@host:5432/db` |

---

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Авторизация — запрашивает пароль |
| `/help` | Справка по использованию |
| `/history` | История транскрибаций с навигацией |
| `/cost` | Стоимость последней транскрибации |
| `/logout` | Выход из системы |

---

## Ограничения

| Параметр | Лимит |
|---|---|
| Макс. длительность аудио | 4 часа (авто-разделение) |
| Макс. размер файла | 2 ГБ (лимит Telegram) |
| Макс. пользователей | 20 |
| Язык распознавания | Только русский (ru-RU) |
| Поддерживаемые аудиоформаты | OGG, MP3, WAV, FLAC, M4A |
| Поддерживаемые видеоформаты | MP4, AVI, MOV, MKV, WEBM |

---

## Стоимость использования

> Подробная разбивка по сервисам Yandex AI Studio и инфраструктуре — см. раздел **«Ответы на вопросы команды»** выше (пункты 3 и 4).

**Кратко:** обработка 30-минутного аудио обходится в **~6-7 ₽** (SpeechKit + YandexGPT). Ежемесячные расходы на инфраструктуру (VM + Docker PostgreSQL) — **~800-1 500 ₽**.

---

## Будущие планы (v2)

- **Распознавание спикеров (diarization)** — разметка «кто говорит»
- **Адаптивные промпты** — разные форматы анализа для интервью, совещаний, лекций
- **Мультиязычность** — поддержка других языков
- **Интеграция с ViWork** — страница транскрибации в корпоративной системе
- **Яндекс.Мессенджер** — второй интерфейс доставки
- **Стриминговое распознавание** — транскрибация в реальном времени

---

## Разработка

```bash
# Установить все зависимости (включая dev)
uv sync --all-extras

# Запустить тесты
uv run python -m pytest -v

# Запустить конкретный модуль
uv run python -m pytest src/services/test_speechkit.py -v
```

## Лицензия

Внутренний проект.
