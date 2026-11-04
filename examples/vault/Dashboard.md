# 🧠 База знаний

`BUTTON[git-pull, git-sync]`

```meta-bind-button
id: git-pull
label: Получить
icon: download
style: default
hidden: true
actions:
  - type: command
    command: obsidian-git:pull
```

```meta-bind-button
id: git-sync
label: Отправить
icon: upload
style: primary
hidden: true
actions:
  - type: command
    command: obsidian-git:commit-and-sync
```

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

  const toDay = (value) => {
    if (value == null) return null
    if (typeof value.toFormat === "function") return value.startOf("day")
    if (value instanceof Date) return dv.date(value.toISOString().slice(0, 10))
    return dv.date(String(value).trim().slice(0, 10))
  }

  const items = Array.from(rows).map((row) => ({
    date: toDay(row.date),
    kind: String(row.kind ?? "").trim(),
    amount: Number(row.amount) || 0,
    category: String(row.category ?? "").trim(),
    note: String(row.note ?? "").trim()
  }))

  items.sort((a, b) => (b.date?.toMillis?.() ?? 0) - (a.date?.toMillis?.() ?? 0))

  let totalIn = 0
  let totalOut = 0
  for (const item of items) {
    if (item.kind === "income") totalIn += item.amount
    if (item.kind === "expense") totalOut += item.amount
  }

  dv.paragraph(
    `Доход **${totalIn.toLocaleString("ru-RU")} ₽** · Расход **${totalOut.toLocaleString(
      "ru-RU"
    )} ₽** · Итого **${(totalIn - totalOut).toLocaleString("ru-RU")} ₽**`
  )

  const labels = []
  const income = []
  const expense = []
  const index = {}
  const today = dv.date("today").startOf("day")
  const monthStart = today.startOf("month")

  for (let day = monthStart; day <= today; day = day.plus({ days: 1 })) {
    const key = day.toFormat("yyyy-MM-dd")
    index[key] = labels.length
    labels.push(day.toFormat("dd"))
    income.push(0)
    expense.push(0)
  }

  for (const item of items) {
    if (!item.date) continue
    const position = index[item.date.toFormat("yyyy-MM-dd")]
    if (position === undefined) continue
    if (item.kind === "income") income[position] += item.amount
    if (item.kind === "expense") expense[position] += item.amount
  }

  if (typeof window.renderChart === "function") {
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
  }

  dv.table(
    ["Дата", "Тип", "Сумма", "Категория", "Заметка"],
    items.slice(0, 12).map((item) => [
      item.date ? item.date.toFormat("dd.MM.yyyy") : "",
      item.kind === "income" ? "Доход" : "Расход",
      `${item.kind === "income" ? "+" : "−"}${item.amount.toLocaleString("ru-RU")} ₽`,
      item.category,
      item.note
    ])
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
