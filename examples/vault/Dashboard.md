# 🧠 База знаний

```dataviewjs
const pages = dv.pages()
const notes = pages.where((p) => p.created).length
const inbox = pages.where((p) => String(p.file.folder).includes("00_Inbox")).length
let open = 0
let done = 0
for (const p of pages) {
  for (const t of p.file.tasks ?? []) {
    if (t.completed) done++
    else open++
  }
}
const tags = new Set()
for (const p of pages) {
  for (const t of p.file.tags ?? []) tags.add(t)
}
dv.paragraph(
  `**${notes}** заметок · **${inbox}** в инбоксе · **${open}** задач · **${tags.size}** тегов`
)
```

---

## 📥 Инбокс

```dataview
TABLE WITHOUT ID
  file.link AS "Заметка",
  category AS "Категория",
  tags AS "Теги",
  created AS "Создано"
FROM ""
WHERE contains(file.folder, "00_Inbox")
SORT created DESC
```

---

## ✅ Задачи

```dataview
TASK
FROM ""
WHERE !completed
SORT file.name ASC
```

---

## 📈 Активность

```dataviewjs
if (typeof window.renderChart === "function") {
  const byDay = {}
  for (const p of dv.pages()) {
    const d = p.created
    if (!d) continue
    const key =
      typeof d.toFormat === "function" ? d.toFormat("yyyy-MM-dd") : String(d).slice(0, 10)
    byDay[key] = (byDay[key] ?? 0) + 1
  }
  const keys = Object.keys(byDay).sort().slice(-14)
  window.renderChart(
    {
      type: "bar",
      data: {
        labels: keys.map((k) => k.slice(8) + "." + k.slice(5, 7)),
        datasets: [
          {
            label: "Заметок",
            data: keys.map((k) => byDay[k]),
            backgroundColor: "#7c6cff",
            borderRadius: 6
          }
        ]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    },
    this.container
  )
}
```

```dataviewjs
if (typeof window.renderChart === "function") {
  const counts = {}
  for (const p of dv.pages()) {
    if (!p.category) continue
    counts[p.category] = (counts[p.category] ?? 0) + 1
  }
  const labels = Object.keys(counts)
  window.renderChart(
    {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [
          {
            data: labels.map((l) => counts[l]),
            backgroundColor: ["#7c6cff", "#4ec9b0", "#e5c07b", "#e06c75", "#61afef"],
            borderWidth: 0
          }
        ]
      },
      options: { plugins: { legend: { position: "bottom" } }, cutout: "62%" }
    },
    this.container
  )
}
```

```dataviewjs
if (typeof window.renderChart === "function") {
  const counts = {}
  for (const p of dv.pages()) {
    for (const t of p.file.tags ?? []) {
      const name = t.replace("#", "")
      counts[name] = (counts[name] ?? 0) + 1
    }
  }
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10)
  window.renderChart(
    {
      type: "bar",
      data: {
        labels: top.map((e) => e[0]),
        datasets: [
          {
            label: "Упоминаний",
            data: top.map((e) => e[1]),
            backgroundColor: "#4ec9b0",
            borderRadius: 6
          }
        ]
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    },
    this.container
  )
}
```

```dataviewjs
if (typeof window.renderChart === "function") {
  let done = 0
  let open = 0
  for (const p of dv.pages()) {
    for (const t of p.file.tasks ?? []) {
      if (t.completed) done++
      else open++
    }
  }
  window.renderChart(
    {
      type: "doughnut",
      data: {
        labels: ["Сделано", "Осталось"],
        datasets: [
          { data: [done, open], backgroundColor: ["#4ec9b0", "#e06c75"], borderWidth: 0 }
        ]
      },
      options: { plugins: { legend: { position: "bottom" } }, cutout: "62%" }
    },
    this.container
  )
}
```

---

## 📄 Последние

```dataview
LIST
FROM ""
WHERE file.name != "Dashboard"
SORT created DESC
LIMIT 8
```
