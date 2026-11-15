import "./style.css";
import { parts } from "./data.js";
import { formatPrice } from "./format.js";

const rows = parts();
const body = document.querySelector("#parts tbody");

function render(list) {
  body.replaceChildren(
    ...list.map((p) => {
      const tr = document.createElement("tr");
      for (const v of [p.name, p.bin, p.count, formatPrice(p.price)]) {
        const td = document.createElement("td");
        td.textContent = v;
        tr.append(td);
      }
      if (p.count < 20) tr.className = "low";
      return tr;
    }),
  );
  const total = list.reduce((s, p) => s + p.count * p.price, 0);
  document.querySelector("#summary").textContent =
    `${list.length} parts, stock value ${formatPrice(total)}`;
}

render(rows);
