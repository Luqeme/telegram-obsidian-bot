# 🏠 Дашборд

Это просто навигация по базе — ничего настраивать не нужно. Таблицы и графики собираются сами из твоих заметок.

> Если данные выглядят устаревшими: `Ctrl+P` → **Dataview: Force refresh all views**.
>
> Для графиков нужен плагин **Charts**, для таблиц — **Dataview**.

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

## 📈 Графики

### Заметки за последние 14 дней

```dataviewjs
if (typeof window.renderChart !== "function") {
  dv.paragraph("⚠️ Нужен плагин **Charts** — установи и включи его в настройках.")
} else {
  const byDay = {}
  for (const p of dv.pages()) {
    const d = p.created
    if (!d) continue
    const key = typeof d.toFormat === "function" ? d.toFormat("yyyy-MM-dd") : String(d).slice(0, 10)
    byDay[key] = (byDay[key] ?? 0) + 1
  }
  const keys = Object.keys(byDay).sort().slice(-14)
  window.renderChart({
    type: "bar",
    data: {
      labels: keys.map((k) => k.slice(8) + "." + k.slice(5, 7)),
      datasets: [{
        label: "Заметок",
        data: keys.map((k) => byDay[k]),
        backgroundColor: "#7c6cff",
        borderRadius: 4
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
    }
  }, this.container)
}
```

### Категории

```dataviewjs
if (typeof window.renderChart !== "function") {
  dv.paragraph("⚠️ Нужен плагин **Charts**.")
} else {
  const counts = {}
  for (const p of dv.pages()) {
    if (!p.category) continue
    counts[p.category] = (counts[p.category] ?? 0) + 1
  }
  const labels = Object.keys(counts)
  window.renderChart({
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: labels.map((l) => counts[l]),
        backgroundColor: ["#7c6cff", "#4ec9b0", "#e5c07b", "#e06c75", "#61afef"]
      }]
    },
    options: { plugins: { legend: { position: "bottom" } } }
  }, this.container)
}
```

### Топ тегов

```dataviewjs
if (typeof window.renderChart !== "function") {
  dv.paragraph("⚠️ Нужен плагин **Charts**.")
} else {
  const counts = {}
  for (const p of dv.pages()) {
    for (const t of p.file.tags ?? []) {
      const name = t.replace("#", "")
      counts[name] = (counts[name] ?? 0) + 1
    }
  }
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10)
  window.renderChart({
    type: "bar",
    data: {
      labels: top.map((e) => e[0]),
      datasets: [{
        label: "Упоминаний",
        data: top.map((e) => e[1]),
        backgroundColor: "#4ec9b0",
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
    }
  }, this.container)
}
```

### Задачи: сделано и осталось

```dataviewjs
if (typeof window.renderChart !== "function") {
  dv.paragraph("⚠️ Нужен плагин **Charts**.")
} else {
  let done = 0
  let open = 0
  for (const p of dv.pages()) {
    for (const t of p.file.tasks ?? []) {
      if (t.completed) done++
      else open++
    }
  }
  window.renderChart({
    type: "doughnut",
    data: {
      labels: ["Сделано", "Осталось"],
      datasets: [{
        data: [done, open],
        backgroundColor: ["#4ec9b0", "#e06c75"]
      }]
    },
    options: { plugins: { legend: { position: "bottom" } } }
  }, this.container)
}
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
