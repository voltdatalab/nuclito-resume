import React, { useEffect, useState } from 'react';
import axios from 'axios';
import './App.css';
import Spinner from './Resources/spinner'; // Make sure this path is correct

function App() {
  const [htmlContent, setHtmlContent] = useState('');
  const [loading, setLoading] = useState(true); // Add a loading state

  useEffect(() => {
    setLoading(true); // Set loading to true when the component mounts and the fetch starts
    axios.get(process.env.REACT_APP_API_URL)
      .then(response => {
        setHtmlContent(response.data); // Update state with the HTML content
        setLoading(false); // Set loading to false once data is received
      })
      .catch(error => {
        console.error('There was an error!', error);
        setLoading(false); // Also set loading to false if there's an error
      });
  }, []); // The empty array ensures this effect runs only once after the initial render

  return (
    <div className="App">
      {loading ? (
        <Spinner message="Carregando um caminhão de magia..." />
      ) : (
        // Safely render the HTML content from the server once loading is false
        <div dangerouslySetInnerHTML={{ __html: htmlContent }} />
      )}
    </div>
  );
}

export default App;
