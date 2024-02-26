import React from 'react';
import '../App.css'; // Ensure the path matches where you saved the CSS

const Spinner = ({ message }) => (
  <div className="spinner-container">
    <div className="spinner"></div>
    <p className="spinner-message">{message}</p>
  </div>
);

export default Spinner;
