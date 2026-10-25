// Modern Web Starter - task list logic
(function () {
  "use strict";

  const form = document.getElementById("task-form");
  const input = document.getElementById("task-input");
  const list = document.getElementById("task-list");
  const count = document.getElementById("task-count");
  let tasks = [];

  function render() {
    list.innerHTML = "";
    tasks.forEach(function (task) {
      const li = document.createElement("li");
      li.textContent = task.text;
      li.className =
        "task-item rounded-lg bg-slate-50 px-3 py-2 cursor-pointer select-none";
      if (task.done) {
        li.classList.add("task-done");
      }
      li.addEventListener("click", function () {
        task.done = !task.done;
        render();
      });
      list.appendChild(li);
    });
    const done = tasks.filter(function (t) {
      return t.done;
    }).length;
    count.textContent =
      tasks.length +
      (tasks.length === 1 ? " task" : " tasks") +
      ", " +
      done +
      " done";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      return;
    }
    tasks.push({ text: text, done: false });
    input.value = "";
    render();
  });

  render();
})();
