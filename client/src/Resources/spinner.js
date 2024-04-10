import React from "react";
import "../App.css"; // Ensure the path matches where you saved the CSS

const Spinner = ({ lang }) => (
  <div className="spinner-container">
    <div className="spinner"></div>
    <p className="spinner-message">
      {lang === "pt_BR"
        ? "Carregando um caminhão de magia..."
        : "Loading a metric ton of content..."}
    </p>
  </div>
);

export default Spinner;
