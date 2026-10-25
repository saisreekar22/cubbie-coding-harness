import React, { useState } from "react";

const styles = {
  page: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#f1f5f9",
    fontFamily: "system-ui, -apple-system, sans-serif",
    color: "#0f172a",
    margin: 0,
  },
  card: {
    background: "#ffffff",
    borderRadius: "16px",
    boxShadow: "0 10px 25px rgba(15, 23, 42, 0.1)",
    padding: "32px",
    textAlign: "center",
    width: "320px",
  },
  title: {
    fontSize: "24px",
    fontWeight: 700,
    margin: "0 0 8px 0",
  },
  subtitle: {
    fontSize: "14px",
    color: "#64748b",
    margin: "0 0 24px 0",
  },
  count: {
    fontSize: "48px",
    fontWeight: 700,
    margin: "0 0 24px 0",
    color: "#4f46e5",
  },
};

function App() {
  const [count, setCount] = useState(0);

  return (
    <main style={styles.page}>
      <section style={styles.card}>
        <h1 style={styles.title}>React SPA Starter</h1>
        <p style={styles.subtitle}>Vite + React, ready to build.</p>
        <p style={styles.count}>{count}</p>
        <button
          onClick={() => setCount((c) => c + 1)}
          style={{
            border: "none",
            borderRadius: "8px",
            background: "#4f46e5",
            color: "#ffffff",
            cursor: "pointer",
            fontSize: "16px",
            fontWeight: 600,
            padding: "10px 24px",
          }}
        >
          Increment
        </button>
      </section>
    </main>
  );
}

export default App;
