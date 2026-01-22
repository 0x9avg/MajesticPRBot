"""
Скрипт для создания тестовых данных PR (12 сотрудников).
Запускать из директории services/api
"""

import asyncio
import aiomysql
from datetime import datetime, timedelta
import random

# Конфигурация БД (берем из .env)
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',  # ЗАМЕНИТЕ на ваш пароль
    'db': 'remote_control',
    'charset': 'utf8mb4',
}

# Тестовые данные
NICKNAMES = [
    'Александр_Р',
    'Мария_К',
    'Дмитрий_С',
    'Анна_В',
    'Игорь_М',
    'Елена_П',
    'Сергей_Л',
    'Ольга_Н',
    'Владимир_Б',
    'Наталья_Ж',
    'Андрей_Т',
    'Екатерина_Ф'
]

ROLES = ['employee', 'senior_employee', 'manager', 'developer']

STREAMERS = [
    'GTA5RP_Master',
    'RolePlayKing',
    'StreamerPro',
    'TwitchGamer',
    'LiveContent',
]

EVENTS = [
    'Новогодний турнир',
    'Гонка на выживание',
    'Музыкальный фестиваль',
    'Квест-марафон',
]


async def create_test_assistants():
    """Создание 12 тестовых PR с разными данными."""
    
    print("🔗 Подключение к базе данных...")
    conn = await aiomysql.connect(**DB_CONFIG)
    cursor = await conn.cursor()
    
    try:
        print("🗑️  Пересоздание таблицы assistants...")
        await cursor.execute("DROP TABLE IF EXISTS assistants")
        
        # Создаем таблицу с новой схемой (как в database.py)
        await cursor.execute(
            """
            CREATE TABLE assistants (
                pr_id BIGINT UNSIGNED PRIMARY KEY,
                nickname VARCHAR(100) NOT NULL,
                role ENUM('employee', 'senior_employee', 'manager', 'developer') NOT NULL,
                experience_days INT DEFAULT 0,
                status ENUM('free', 'assigned') DEFAULT 'free',
                assigned_to_type ENUM('streamer', 'event') NULL,
                assigned_to_id BIGINT UNSIGNED NULL,
                assigned_to_name VARCHAR(255) NULL,
                total_spec_seconds BIGINT DEFAULT 0,
                session_count INT DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_status (status),
                INDEX idx_role (role)
            )
            """
        )
        await conn.commit()
        print("✅ Таблица успешно обновлена!")
        
        print("👥 Создание 12 PR сотрудников...\n")
        
        for i, nickname in enumerate(NICKNAMES):
            pr_id = 100000000 + i  # Тестовые ID начинаются с 100000000
            
            # Случайная должность с весами (больше обычных сотрудников)
            role = random.choices(
                ROLES,
                weights=[50, 30, 15, 5],  # employee наиболее вероятен
                k=1
            )[0]
            
            # Стаж от 1 до 365 дней
            experience_days = random.randint(1, 365)
            
            # 60% свободны, 40% в закрепе
            is_assigned = random.random() < 0.4
            
            if is_assigned:
                status = 'assigned'
                assigned_type = random.choice(['streamer', 'event'])
                
                if assigned_type == 'streamer':
                    assigned_id = random.randint(200000000, 299999999)
                    assigned_name = random.choice(STREAMERS)
                else:  # event
                    assigned_id = random.randint(1, 100)
                    assigned_name = random.choice(EVENTS)
            else:
                status = 'free'
                assigned_type = None
                assigned_id = None
                assigned_name = None
            
            # Статистика: время спека от 0 до 500 часов (в секундах)
            total_spec_seconds = random.randint(0, 500 * 3600)
            
            # Количество сессий: от 0 до 300
            session_count = random.randint(0, 300)
            
            # Вставка данных
            await cursor.execute(
                """
                INSERT INTO assistants (
                    pr_id, nickname, role, experience_days, status,
                    assigned_to_type, assigned_to_id, assigned_to_name,
                    total_spec_seconds, session_count, added_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    pr_id,
                    nickname,
                    role,
                    experience_days,
                    status,
                    assigned_type,
                    assigned_id,
                    assigned_name,
                    total_spec_seconds,
                    session_count,
                    datetime.now() - timedelta(days=random.randint(0, 180))
                )
            )
            
            # Вывод информации
            status_text = f"🟢 Свободен" if status == 'free' else f"🟣 Закреплен за {assigned_name}"
            hours = total_spec_seconds / 3600
            
            print(f"✅ {i+1}. {nickname}")
            print(f"   Должность: {role}")
            print(f"   Стаж: {experience_days} дней")
            print(f"   Статус: {status_text}")
            print(f"   Статистика: {hours:.1f}ч, {session_count} сессий")
            print()
        
        await conn.commit()
        print("✨ Успешно создано 12 PR сотрудников!")
        print(f"\n📊 Проверьте результат на http://localhost:5173/pr-stats")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        await conn.rollback()
    finally:
        await cursor.close()
        conn.close()
        print("\n🔌 Соединение закрыто")


if __name__ == "__main__":
    print("=" * 60)
    print("🎯 Генератор тестовых данных для PR Stats")
    print("=" * 60)
    print()
    
    # Проверка конфигурации
    if DB_CONFIG['password'] == 'your_password':
        print("⚠️  ВНИМАНИЕ: Не забудьте изменить пароль в DB_CONFIG!")
        print("   Откройте файл и установите правильный пароль MySQL\n")
        input("Нажмите Enter для продолжения или Ctrl+C для отмены...")
    
    asyncio.run(create_test_assistants())
