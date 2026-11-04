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
  link(file.path, default(title, file.name)) AS "Заметка",
  category AS "Категория",
  (date(today) - created).days AS "Дней"
FROM ""
WHERE contains(file.folder, "00_Inbox")
SORT created ASC
```

---

## ✅ Задачи

```dataviewjs
const tasks = []
for (const p of dv.pages()) {
  for (const t of p.file.tasks ?? []) {
    if (!t.completed) tasks.push(t)
  }
}
if (tasks.length) {
  dv.taskList(tasks, false)
} else {
  dv.paragraph("Открытых задач нет.")
}
```

---

## 📈 Активность

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

```dataviewjs
const cutoff = dv.date("today").minus(dv.duration("14 days"))
const hanging = []
for (const p of dv.pages()) {
  const c = p.created
  if (!c) continue
  const d = typeof c.toFormat === "function" ? c : dv.date(String(c))
  if (!d || d > cutoff) continue
  for (const t of p.file.tasks ?? []) {
    if (!t.completed) hanging.push(t)
  }
}
if (hanging.length) {
  dv.header(4, "⏳ Висит больше двух недель")
  dv.taskList(hanging, false)
}
```

```dataviewjs
const skip = ["Dashboard", "README"]
const untagged = dv
  .pages()
  .where((p) => !skip.includes(p.file.name))
  .where((p) => (p.file.tags ?? []).length === 0)
if (untagged.length) {
  dv.header(4, "🏷 Без тегов")
  dv.list(untagged.map((p) => dv.fileLink(p.file.path, false, p.title ?? p.file.name)))
}
```

```dataviewjs
const cutoff = dv.date("today").minus(dv.duration("30 days"))
const stale = dv.pages().where((p) => {
  if (!String(p.file.folder).includes("10_Notes")) return false
  const c = p.created
  if (!c) return false
  const d = typeof c.toFormat === "function" ? c : dv.date(String(c))
  if (!d || d > cutoff) return false
  return (p.file.tasks ?? []).length === 0 && (p.file.outlinks ?? []).length === 0
})
if (stale.length) {
  dv.header(4, "🧊 Без продолжения")
  dv.list(stale.map((p) => dv.fileLink(p.file.path, false, p.title ?? p.file.name)))
}
```

---

## 📄 Последние

```dataview
LIST WITHOUT ID link(file.path, default(title, file.name))
FROM ""
WHERE file.name != "Dashboard"
SORT created DESC
LIMIT 8
```
