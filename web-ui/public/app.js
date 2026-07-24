// Product Catalog — client-side store whose validation mirrors the Products API
// contract (java-component ProductRequest / ProductService), so UI automation
// asserts the same observable behaviour the backend enforces.
(function () {
  "use strict";

  var NAME_MAX = 100;
  var PRICE_CAP = 300000; // DecimalMax("300000.00")

  // Deterministic seed so browser tests can assert exact counts.
  var seq = 0;
  var products = [
    { id: ++seq, name: "Wireless Keyboard", price: 79.99 },
    { id: ++seq, name: "USB-C Hub", price: 45.00 },
    { id: ++seq, name: "4K Monitor", price: 289.00 }
  ];
  var filter = null; // { min: number|null, max: number|null }

  var $ = function (sel) { return document.querySelector(sel); };
  var rowsEl = $("#rows");
  var alertEl = $("#alert");
  var countEl = $("[data-testid=product-count]");
  var emptyEl = $("#empty");

  function money(n) {
    return "$" + n.toFixed(2);
  }

  function showAlert(message, kind) {
    alertEl.textContent = message;
    alertEl.className = "alert " + (kind || "error");
    alertEl.hidden = false;
  }
  function clearAlert() {
    alertEl.hidden = true;
    alertEl.textContent = "";
    alertEl.className = "alert";
  }

  // ---- validation (mirrors ProductRequest bean-validation messages) ----
  function validateProduct(name, priceRaw) {
    var trimmed = (name || "").trim();
    if (trimmed === "") return "name must not be blank";
    if (trimmed.length > NAME_MAX) return "name must not exceed 100 characters";

    if ((priceRaw || "").trim() === "") return "price is required";
    var price = Number(priceRaw);
    if (!isFinite(price)) return "price is required";
    if (price <= 0) return "price must be greater than zero";
    if (price > PRICE_CAP) return "price must not exceed 300000.00";
    return null;
  }

  function validateRange(min, max) {
    if (min !== null && max !== null && min > max) {
      return "minPrice must not be greater than maxPrice";
    }
    return null;
  }

  // ---- rendering ----
  function visibleProducts() {
    return products.filter(function (p) {
      if (!filter) return true;
      if (filter.min !== null && p.price < filter.min) return false;
      if (filter.max !== null && p.price > filter.max) return false;
      return true;
    });
  }

  function render() {
    var list = visibleProducts();
    rowsEl.innerHTML = "";
    list.forEach(function (p) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-testid", "product-row");
      tr.setAttribute("data-name", p.name);
      tr.setAttribute("data-id", String(p.id));
      tr.innerHTML =
        '<td class="name" data-testid="product-name"></td>' +
        '<td class="right price" data-testid="product-price"></td>' +
        '<td class="right"><button class="del" data-testid="delete-btn">Delete</button></td>';
      tr.querySelector(".name").textContent = p.name;
      tr.querySelector(".price").textContent = money(p.price);
      rowsEl.appendChild(tr);
    });
    var n = list.length;
    countEl.textContent = n + (n === 1 ? " product" : " products");
    emptyEl.hidden = n !== 0;
  }

  // ---- handlers ----
  $("#add-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var name = $("#name").value;
    var priceRaw = $("#price").value;
    var error = validateProduct(name, priceRaw);
    if (error) { showAlert(error, "error"); return; }

    products.push({ id: ++seq, name: name.trim(), price: Number(priceRaw) });
    $("#name").value = "";
    $("#price").value = "";
    filter = null;                 // show the full catalog so the new item is visible
    $("#min-price").value = "";
    $("#max-price").value = "";
    render();
    showAlert('Product "' + name.trim() + '" added.', "ok");
  });

  $("[data-testid=apply-filter]").addEventListener("click", function () {
    var minRaw = $("#min-price").value.trim();
    var maxRaw = $("#max-price").value.trim();
    var min = minRaw === "" ? null : Number(minRaw);
    var max = maxRaw === "" ? null : Number(maxRaw);
    if ((min !== null && !isFinite(min)) || (max !== null && !isFinite(max))) {
      showAlert("price filters must be numbers", "error");
      return;
    }
    var error = validateRange(min, max);
    if (error) { showAlert(error, "error"); return; }
    filter = { min: min, max: max };
    clearAlert();
    render();
  });

  $("[data-testid=clear-filter]").addEventListener("click", function () {
    filter = null;
    $("#min-price").value = "";
    $("#max-price").value = "";
    clearAlert();
    render();
  });

  rowsEl.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-testid=delete-btn]");
    if (!btn) return;
    var tr = btn.closest("[data-testid=product-row]");
    var id = Number(tr.getAttribute("data-id"));
    var name = tr.getAttribute("data-name");
    products = products.filter(function (p) { return p.id !== id; });
    render();
    showAlert('Product "' + name + '" removed.', "ok");
  });

  render();
})();
