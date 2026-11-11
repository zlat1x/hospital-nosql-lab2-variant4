"""Turn actual benchmark JSON into a ready-to-review results summary (no fabricated metrics)."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path, help="results/benchmark_*.json")
    args = p.parse_args()
    doc = json.loads(args.input.read_text(encoding="utf-8"))
    rows = doc["results"]
    lines = [
        "# Фактичні результати вимірювання продуктивності SQL і MongoDB",
        "",
        f"Дата (UTC): `{doc['generated_utc']}`.",
        f"Набір: **{doc['dataset']['reports']:,} звітів**, "
        f"**{doc['dataset']['measurements']:,} вимірювань**, "
        f"**{doc['dataset']['patients']} синтетичних пацієнтів**.",
        "",
        f"Середовище: PostgreSQL {doc['environment']['postgres']}, "
        f"MongoDB {doc['environment']['mongodb']}, "
        f"Python {doc['environment']['python']} "
        f"({doc['environment']['platform']}).",
        "",
        "## Таблиця вимірювань",
        "",
        "| Сценарій | SQL p50 (мс) | MongoDB p50 (мс) | SQL p95 (мс) | MongoDB p95 (мс) | Порівняння p50 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sql, mongo in zip(rows[::2], rows[1::2]):
        if sql['workload'] != mongo['workload']:
            raise ValueError('Expected adjacent SQL and MongoDB measurements for the same workload')
        ratio = sql['p50_ms'] / mongo['p50_ms'] if mongo['p50_ms'] else float('nan')
        lines.append(
            f"| {sql['workload']} | {sql['p50_ms']:.4f} | {mongo['p50_ms']:.4f} | "
            f"{sql['p95_ms']:.4f} | {mongo['p95_ms']:.4f} | {ratio:.2f}× |"
        )
    lines += [
        "", "**Інтерпретація:** відношення SQL/MongoDB понад 1 означає, що SQL мав більшу "
        "медіанну затримку в цьому сценарії; менше 1 — навпаки. "
        "Це НЕ універсальна перевага типу бази, а результат конкретного доступу, даних та середовища.",
        "", "## Протокол", "",
        f"- Прогрів: {doc['procedure']['warmups']} викликів; "
        f"читань: {doc['procedure']['read_trials_per_database']} на базу; "
        f"записів: {doc['procedure']['write_trials_per_database']} на базу.",
        "- Чергування порядку SQL/MongoDB, однакова послідовність ключів, один клієнт, "
        "підключення повторно використовувались.",
        "- Вимірювалась клієнтська тривалість операції, включно з мережею localhost "
        "та формуванням результату; завантаження даних, перевірка коректності та cleanup поза таймером.",
        "- SQL нормалізований на 4 таблиці; MongoDB один документ із вкладеними панелями.",
        "- Однакові індекси за бізнесовим доступом, але НЕ тотожні внутрішні структури.",
        "- Генератор детермінований, містить і нормальні, і позадіапазонні значення.",
        "", "## Обмеження та висновок", "",
        "Завершений вимір показує різницю затримки для вибраного зразка, але не враховує "
        "конкуренцію, реплікацію, навантаження диска, холодний кеш, аварійне відновлення "
        "та вартість узгодження двох джерел. Для лікарні критичні транзакції та "
        "довідникові дані доцільно залишити в PostgreSQL. "
        "MongoDB має сенс як окреме сховище обмежених, різнорідних звітів, "
        "які часто читаються цілим агрегатом; необхідно забезпечити надійний "
        "експорт, контроль версій і медичний аудит.",
        "", "**Висновок про швидкодію треба робити окремо для кожного рядка таблиці**, "
        "без автоматичного твердження, що будь-яка NoSQL база швидша.",
        "", "## Відтворення", "",
        f"Первинні дані: `{args.input.name}` та однойменний CSV; "
        "плани виконання у `*_plans.json` (якщо збір вдався).",
    ]
    path = args.input.with_name(args.input.stem + "_analysis.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated report from measured data: {path}")


if __name__ == "__main__":
    main()
