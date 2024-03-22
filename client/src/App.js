import React, { useEffect, useState } from "react";
import axios from "axios";
import "./App.css";
import Spinner from "./Resources/spinner"; // Make sure this path is correct
import Grid from "./Resources/grid";
import SlideShow from "./Resources/slideshow";
import { Helmet } from "react-helmet";
import { Button } from "react-bootstrap";

function App() {
  const [jsonData, setJsonData] = useState([]);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true); // Add a loading state
  const amountPerPage = 6;
  const mobileMaxWidth = 700;
  const [isMobile, setIsMobile] = useState(window.innerWidth < mobileMaxWidth);

  const fetchJsonData = () => {
    axios.get(process.env.REACT_APP_API_URL + "/post/", {
      params: { page: page, amount: amountPerPage },
    })
      .then((response) => {
        setJsonData((prevData) => [...prevData, ...response.data]); // Update state with the HTML content
        setPage((prevPage) => prevPage + 1);
      })
      .catch((error) => {
        console.error("There was an error!", error);
      })
      .finally(setLoading(false)); // Also set loading to false if there's an error
  };

  useEffect(() => {
    setLoading(true); // Set loading to true when the component mounts and the fetch starts
    fetchJsonData();

    const handleResize = () => {
      setIsMobile(window.innerWidth < mobileMaxWidth);
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []); // The empty array ensures this effect runs only once after the initial render

  return (
    <div className="App">
      <Helmet>
        <style>{"body { background-color: #eeeeee; }"}</style>
      </Helmet>
      {loading
        ? <Spinner message="Carregando um caminhão de magia..." />
        : (
          <div>
            {isMobile
              ? <SlideShow posts={jsonData} />
              : <Grid posts={jsonData} />}
            <Button
              onClick={() => fetchJsonData(page)}
              disabled={loading}
            >
              Carregar mais
            </Button>
          </div>
        )}
    </div>
  );
}

export default App;
