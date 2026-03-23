# Прикладные потоки

Этот документ описывает не структуру каталогов и не endpoint catalog, а то, как система реально работает по доменам: какие сервисы участвуют, где хранится источник правды и какие переходы состояния происходят.

Его задача — объяснить сценарии и state transitions. За HTTP-ручки отвечает `api-reference.md`, а за сервисные границы — `architecture.md`.

## Streamers и Twitch sync

### Добавление стримера

Есть два режима создания стримера:

- user/service UI вызывает `POST /api/streamers` с `twitch_url`;
- `twitch_bot` вызывает `POST /api/streamers` в полном режиме с уже известными `streamer_id` и `streamer_name`.

Основной пользовательский сценарий выглядит так:

1. Web или Discord отправляет в API `twitch_url`.
2. API не создает стримера напрямую, а публикует интеграционное событие `streamer.verify` через outbox.
3. `twitch_bot` получает `streamer.verify`, нормализует username, резолвит Twitch user ID, забирает профиль и текущий live-state.
4. `twitch_bot` вызывает API уже в полном режиме создания стримера.
5. API записывает стримера в MySQL и публикует `streamer.added`.
6. `twitch_bot` получает `streamer.added`, подписывает EventSub и делает первичную проверку online/offline статуса.

Это разделение намеренное:

- API остается источником правды для persistent metadata;
- Twitch-specific резолвинг и EventSub orchestration живут в `twitch_bot`;
- outbox защищает доставку событий при временной недоступности RabbitMQ.

### Поддержание live-state

`twitch_bot` синхронизирует состояние двумя способами:

- делает full sync на старте;
- реагирует на Twitch EventSub online/offline/category events во время работы.

Ручной полный sync можно запросить через `POST /api/services/twitch/sync`. Эта ручка не синхронизирует Twitch сама по себе: она публикует `service.twitch.sync`, а фактическую работу выполняет `twitch_bot`.

## Spec-сессии и активные закрепления

### Главный принцип

В проекте нет отдельной постоянной таблицы "кто сейчас закреплен". Текущее состояние и история строятся на одной модели: открытых и закрытых `spec_sessions`.

Это означает:

- активное закрепление = сессия без завершения;
- история работы = те же записи, но уже завершенные;
- duration, reason и другие runtime-атрибуты являются частью основной модели, а не побочным логом.

### Claimable pool

Доступные цели для закрепления формируются из двух источников:

- онлайн-стримеры, особенно в GTA 5;
- активные события, у которых еще есть свободные PR slots.

Мониторинговая read-model строится API и используется Discord/Web как готовый view-model, а не собирается на клиенте из нескольких ручек.

### Claim / unclaim

Базовые ручки:

- `POST /api/spec/claim`
- `POST /api/spec/claim/{pr_id}`
- `POST /api/spec/unclaim`
- `POST /api/spec/unclaim/{pr_id}`

Паттерн такой:

- пользовательские ручки работают от текущего аутентифицированного сотрудника;
- service/admin-варианты позволяют работать с целевым `pr_id`;
- API проверяет permissions, бизнес-ограничения по слотам и пишет изменение в `spec_sessions`;
- при завершении сессии фиксируются duration и end reason.

Для стримеров модель допускает main/probation слоты. Для событий используется тот же runtime-контур, но источник назначения другой.

## Events и spec requests

### Обычные события

Событие создается через `POST /api/events`. Дальше для него доступны:

- просмотр;
- изменение;
- join/leave участников;
- `start`;
- `end`;
- отметка отправки уведомления.

### Pending participants до старта

До старта участники живут не в активных `spec_sessions`, а в event reservation слое:

- `join` может либо сразу присоединить, либо зарезервировать слот;
- `leave` снимает резерв или активное участие, в зависимости от состояния события.

### Что делает `start`

`POST /api/events/{event_id}/start` переводит событие в runtime-фазу:

- reserved participants мигрируют в активные `spec_sessions`;
- после этого событие начинает участвовать в тех же расчетах занятости и статистики, что и streamer-based spec.

### Что делает `end`

`POST /api/events/{event_id}/end` завершает связанные runtime-сессии и фиксирует длительность участия по каждому PR.

### Spec request

`spec_request` это не отдельный сервис, а частный сценарий event workflow:

1. сотрудник создает `POST /api/events/spec-request`;
2. API создает pending event request;
3. ревьюер видит его через `GET /api/events/pending`;
4. затем либо обновляет pending-данные, либо `approve`, либо `reject`;
5. после `approve` заявка превращается в обычный event runtime-flow.

## Web auth и сессии

### Как устроена авторизация

Контракт разделен на две части:

- access token живет только в памяти web-клиента;
- refresh token хранится в HttpOnly cookie `refresh_token`.

Основные ручки:

- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout/current`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/auth/sessions`
- `POST /api/auth/sessions/{sid}/revoke`

### Rotation и reuse detection

Каждый refresh:

1. проверяет текущую session chain;
2. создает новый refresh token;
3. помечает предыдущую сессию как replaced;
4. выдает новый access token с новым `sid`.

Если старый refresh token используется повторно, API считает это reuse и отзывает всю family сессий. Это важная часть security-модели проекта.

### Поведение web-клиента

Web-клиент:

- делает proactive refresh перед истечением access token;
- делает reactive refresh на `401 TOKEN_EXPIRED`, `TOKEN_INVALID`, `SESSION_REVOKED`;
- делает hard logout при `REFRESH_REUSE_DETECTED`;
- отдельно обрабатывает `503 SITE_MAINTENANCE`.

## Returns workflow

`returns` покрывают возврат ранее снятого наказания после выдержки окна ожидания.

Основной поток:

1. сотрудник создает запись возврата;
2. запись попадает в queue;
3. после required waiting window становится доступной к обработке;
4. исполнитель берет запись в работу (`claim`);
5. затем завершает (`complete`) или освобождает (`release`);
6. завершенная запись уходит в history.

API одновременно хранит:

- доменные данные возврата;
- вычисленные команды вида `/unjail`, `/unmute`, `/ajail`, `/mute`;
- флаги `can_claim`, `can_complete`, `can_release`, `can_edit`, `can_delete` для UI.

## Complaints workflow

`complaints` это workflow по media-жалобам с набором наказаний.

Основные стадии:

- draft;
- pending;
- issued/completed.

Внутри записи API формирует:

- доменные поля жалобы;
- набор наказаний;
- preview server commands;
- готовые message lines для публикации результата;
- UI capability flags, зависящие от роли и стадии.

Это важно: большая часть прикладной логики complaint workflow находится в API/DB, а не во фронтенде.

## Removals workflow

`removals` обслуживают выдачу снятий наказаний (`/unjail`, `/unmute`) как отдельный управляемый workflow.

Стадии:

- `draft`
- `pending`
- `issued`

Правила прав доступа зависят от:

- авторства записи;
- текущего статуса;
- наличия `manage.self`, `manage.any`, `issue`.

Как и в `complaints`, API возвращает уже обогащенный record с `command`, `status_label`, `status_date` и capability flags для UI.

## Sanctions и sanctions_worker

### Что делает API

API отвечает за:

- санкционный ledger;
- ручную выдачу санкций;
- relief/replace сценарии;
- месячные настройки политики;
- правила check cycles;
- операции массовой выдачи (`sanction-operations`).

### Что делает `sanctions_worker`

`sanctions_worker` это отдельный процесс, а не background task внутри API. Он выполняет две разные задачи:

- раз в цикл пытается обработать nightly queued batches за предыдущий день;
- слушает RabbitMQ routing key `sanction.operation.issue_now` и обрабатывает manual issue-now requests.

### Issue now flow

1. Пользователь вызывает `POST /api/sanction-operations/{operation_id}/issue-now`.
2. API валидирует, что операция существует и имеет статус `queued`.
3. API публикует событие `sanction.operation.issue_now`.
4. `sanctions_worker` получает сообщение и вызывает DB processing.
5. Результат фиксируется в MySQL и аудит-логах.

Если worker не запущен, queued/nightly контур будет неполным даже при полностью работающем API.

## Assistant weekly

Weekly read-model строится поверх уже накопленных runtime-данных:

- spec session slices;
- mchat/day adjustments;
- complaints;
- санкционные статусы и payout-правила.

Есть две основные зоны:

- `GET /api/assistant-weekly/current` для пользовательского обзора;
- `GET/PUT /api/assistant-weekly/admin*` для review и payout management.

Admin weekly review позволяет:

- задавать manual day overrides;
- выбирать итоговый результат недели;
- задавать payout parameters;
- фиксировать payout issue status.

Смысл weekly-контура в том, что он не хранит "самостоятельную статистику" отдельно от доменной модели. Он собирает и нормализует данные из уже существующих runtime-источников.

## Service monitoring

Discord и Twitch боты каждые 30 секунд отправляют heartbeat в `POST /api/services/heartbeat`.

API объединяет:

- свой runtime snapshot;
- service registry из последних heartbeat;
- прикладные domain counters.

Результат доступен через `GET /api/services/overview`.

Нужно учитывать caveat: registry хранится в памяти API-процесса. После рестарта API другие сервисы до следующего heartbeat будут отображаться как `offline`, а после превышения stale-window как `stale`.
