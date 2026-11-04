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

```dataviewjs
const today = dv.date("today").startOf("day")
const pages = dv
  .pages()
  .where((p) => String(p.file.folder).includes("00_Inbox"))
  .sort((p) => p.created, "asc")

const rows = pages.map((p) => {
  const created = p.created
  let days = ""
  if (created && typeof created.toFormat === "function") {
    days = Math.round(today.diff(created.startOf("day"), "days").days)
  }
  return [dv.fileLink(p.file.path, false, p.title ?? p.file.name), p.category ?? "", days]
})

dv.table(["Заметка", "Категория", "Дней"], rows)
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

## 💰 Деньги

```dataviewjs
const container = this.container

;(async () => {
  let rows = []
  try {
    rows = (await dv.io.csv("30_Money/transactions.csv")) ?? []
  } catch (error) {
    rows = []
  }

  if (!rows.length) {
    dv.paragraph("Пока нет записей.")
    return
  }

  const days = 14
  const labels = []
  const income = []
  const expense = []
  const index = {}
  const today = dv.date("today")

  for (let i = days - 1; i >= 0; i--) {
    const day = today.minus(dv.duration(`${i} days`))
    const key = day.toFormat("yyyy-MM-dd")
    index[key] = labels.length
    labels.push(day.toFormat("dd.MM"))
    income.push(0)
    expense.push(0)
  }

  let totalIn = 0
  let totalOut = 0

  for (const row of rows) {
    const amount = Number(row.amount) || 0
    if (row.kind === "income") totalIn += amount
    if (row.kind === "expense") totalOut += amount

    const position = index[row.date]
    if (position === undefined) continue
    if (row.kind === "income") income[position] += amount
    if (row.kind === "expense") expense[position] += amount
  }

  dv.paragraph(
    `Доход **${totalIn.toLocaleString("ru-RU")} ₽** · Расход **${totalOut.toLocaleString(
      "ru-RU"
    )} ₽** · Итого **${(totalIn - totalOut).toLocaleString("ru-RU")} ₽**`
  )

  if (typeof window.renderChart !== "function") return

  window.renderChart(
    {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Доход",
            data: income,
            backgroundColor: "#4ec9b0",
            borderRadius: 6
          },
          {
            label: "Расход",
            data: expense,
            backgroundColor: "#e06c75",
            borderRadius: 6
          }
        ]
      },
      options: {
        plugins: { legend: { position: "bottom" } },
        scales: { y: { beginAtZero: true } }
      }
    },
    container
  )
})()
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
