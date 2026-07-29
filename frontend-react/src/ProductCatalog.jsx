import { useMemo, useState } from "react";

// Validation mirrors the Products API contract (java-component ProductRequest /
// ProductService), so UI automation asserts the same observable behaviour the
// backend enforces — regardless of the fact this frontend is React.
const NAME_MAX = 100;
const PRICE_CAP = 300000; // DecimalMax("300000.00")

const SEED = [
  { id: 1, name: "Wireless Keyboard", price: 79.99 },
  { id: 2, name: "USB-C Hub", price: 45.0 },
  { id: 3, name: "4K Monitor", price: 289.0 }
];

const money = (n) => "$" + n.toFixed(2);

function validateProduct(name, priceRaw) {
  const trimmed = (name || "").trim();
  if (trimmed === "") return "name is required";
  if (trimmed.length > NAME_MAX) return "name must not exceed 100 characters";
  if (trimmed.length < 2) return "name must be at least 2 characters";
  if ((priceRaw || "").trim() === "") return "price is required";
  const price = Number(priceRaw);
  if (!Number.isFinite(price)) return "price is required";
  if (price <= 0) return "price must be greater than zero";
  if (price > PRICE_CAP) return "price must not exceed 400000.00";
  return null;
}

export default function ProductCatalog() {
  const [products, setProducts] = useState(SEED);
  const [seq, setSeq] = useState(SEED.length);
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [filter, setFilter] = useState(null);
  const [alert, setAlert] = useState(null); // { kind: "error" | "ok", message }

  const visible = useMemo(
    () =>
      products.filter((p) => {
        if (!filter) return true;
        if (filter.min !== null && p.price < filter.min) return false;
        if (filter.max !== null && p.price > filter.max) return false;
        return true;
      }),
    [products, filter]
  );

  function addProduct(e) {
    e.preventDefault();
    const error = validateProduct(name, price);
    if (error) return setAlert({ kind: "error", message: error });
    const id = seq + 1;
    const added = name.trim();
    setSeq(id);
    setProducts([...products, { id, name: added, price: Number(price) }]);
    setName("");
    setPrice("");
    setFilter(null); // show the full catalog so the new item is visible
    setMinPrice("");
    setMaxPrice("");
    setAlert({ kind: "ok", message: `Product "${added}" added.` });
  }

  function applyFilter() {
    const min = minPrice.trim() === "" ? null : Number(minPrice);
    const max = maxPrice.trim() === "" ? null : Number(maxPrice);
    if ((min !== null && !Number.isFinite(min)) || (max !== null && !Number.isFinite(max))) {
      return setAlert({ kind: "error", message: "price filters must be numbers" });
    }
    if (min !== null && max !== null && min > max) {
      return setAlert({ kind: "error", message: "minPrice must not be greater than maxPrice" });
    }
    setFilter({ min, max });
    setAlert(null);
  }

  function clearFilter() {
    setFilter(null);
    setMinPrice("");
    setMaxPrice("");
    setAlert(null);
  }

  function remove(p) {
    setProducts(products.filter((x) => x.id !== p.id));
    setAlert({ kind: "ok", message: `Product "${p.name}" removed.` });
  }

  const n = visible.length;

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo">◧</span>
          <div>
            <h1>Product Catalog</h1>
            <p className="sub">React frontend — same contract, same UI tests.</p>
          </div>
        </div>
        <span className="count-badge" data-testid="product-count">
          {n} {n === 1 ? "product" : "products"}
        </span>
      </header>

      <main className="layout">
        <section className="panel">
          <h2>Add a product</h2>
          <form onSubmit={addProduct} noValidate>
            <label>
              <span>Name</span>
              <input
                type="text"
                data-testid="name-input"
                placeholder="e.g. Wireless Mouse"
                autoComplete="off"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              <span>Price</span>
              <input
                type="text"
                data-testid="price-input"
                inputMode="decimal"
                placeholder="e.g. 49.99"
                autoComplete="off"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </label>
            <button type="submit" className="primary" data-testid="add-btn">
              Add product
            </button>
          </form>

          <div className="filter">
            <h3>Filter by price</h3>
            <div className="filter-row">
              <input
                type="text"
                data-testid="min-price"
                inputMode="decimal"
                placeholder="Min"
                autoComplete="off"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
              />
              <span className="dash">–</span>
              <input
                type="text"
                data-testid="max-price"
                inputMode="decimal"
                placeholder="Max"
                autoComplete="off"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
              />
              <button type="button" data-testid="apply-filter" onClick={applyFilter}>
                Apply
              </button>
              <button type="button" className="ghost" data-testid="clear-filter" onClick={clearFilter}>
                Clear
              </button>
            </div>
          </div>

          {alert && (
            <div className={"alert " + alert.kind} data-testid="alert" role="alert" aria-live="polite">
              {alert.message}
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Catalog</h2>
          <table className="catalog">
            <thead>
              <tr>
                <th>Name</th>
                <th className="right">Price</th>
                <th aria-label="actions"></th>
              </tr>
            </thead>
            <tbody data-testid="rows">
              {visible.map((p) => (
                <tr key={p.id} data-testid="product-row" data-name={p.name} data-id={p.id}>
                  <td className="name" data-testid="product-name">
                    {p.name}
                  </td>
                  <td className="right price" data-testid="product-price">
                    {money(p.price)}
                  </td>
                  <td className="right">
                    <button className="del" data-testid="delete-btn" onClick={() => remove(p)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {n === 0 && (
            <p className="empty" data-testid="empty">
              No products match.
            </p>
          )}
        </section>
      </main>
    </>
  );
}
