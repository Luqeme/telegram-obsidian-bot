# 🏠 Дашборд

Это просто навигация по базе — ничего настраивать не нужно. Таблицы собираются сами из твоих заметок.

> Если данные выглядят устаревшими: `Ctrl+P` → **Dataview: Force refresh all views**.

---

## 📥 Инбокс — разобрать

Правило: **раз в неделю здесь должен быть ноль.**

```dataview
TABLE WITHOUT ID
  file.link AS "Заметка",
  category AS "Категория",
  tags AS "Теги",
  created AS "Когда"
FROM ""
WHERE contains(file.folder, "00_Inbox")
SORT created DESC
```

> Поле `status:` в шапке — служебное, его ставит бот. Трогать не нужно.

**Как разобрать заметку — одно действие:**

1. Открой её, прочитай
2. Перенеси файл в нужную папку: правый клик → **Move file to…**
   *(на телефоне: долгое нажатие на файл → Move file)*

Всё. Заметка исчезла из инбокса, потому что уехала из папки.

| Куда | Что кладём |
|---|---|
| `10_Notes` | идеи и мысли, к которым вернёшься |
| `20_Projects` | задачи и дела по активным проектам |
| `90_Archive` | отработано, но удалять жалко |
| корзина | если через неделю не вспомнил, о чём это — туда |

---

## ✅ Задачи из инбокса

```dataview
TASK
FROM ""
WHERE contains(file.folder, "00_Inbox") AND !completed
```

## ✅ Все открытые задачи

```dataview
TASK
FROM ""
WHERE !completed AND !contains(file.folder, "00_Inbox")
```

---

## 🕒 Залежалось — старше 7 дней

Если здесь что-то есть, инбокс пора разобрать.

```dataview
TABLE WITHOUT ID
  file.link AS "Заметка",
  created AS "Создано"
FROM ""
WHERE contains(file.folder, "00_Inbox") AND created < date(today) - dur(7 days)
SORT created ASC
```

---

## 📊 Что в базе по категориям

```dataview
TABLE WITHOUT ID
  category AS "Категория",
  length(rows) AS "Заметок"
FROM ""
WHERE category
GROUP BY category
SORT length(rows) DESC
```

## 🏷 Теги

```dataview
TABLE WITHOUT ID
  tag AS "Тег",
  length(rows) AS "Заметок"
FLATTEN file.tags AS tag
WHERE tag
GROUP BY tag
SORT length(rows) DESC
LIMIT 30
```

---

## 📄 Последние заметки

```dataview
LIST
FROM ""
WHERE file.name != "Dashboard"
SORT created DESC
LIMIT 10
```
