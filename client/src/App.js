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

  const lang = process.env.REACT_APP_LANGUAGE
    ? process.env.REACT_APP_LANGUAGE
    : "pt_BR";

  const fetchJsonData = () => {
    axios.get(process.env.REACT_APP_API_URL + "/post/", {
      params: { page: page, amount: amountPerPage },
    })
      .then((response) => {
        setJsonData((prevData) => [...prevData, ...response.data]); // Update state with the JSON content
        setPage((prevPage) => prevPage + 1);
        setLoading(false);
      })
      .catch((error) => {
        console.error("There was an error!", error);
        setLoading(false); // Also set loading to false if there's an error
      });
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
      {loading ? <Spinner lang={lang} /> : (
        <div>
          {isMobile
            ? <SlideShow posts={jsonData} lang={lang} />
            : <Grid posts={jsonData} lang={lang} />}
          <Button
            onClick={() => fetchJsonData(page)}
            disabled={loading}
          >
            {lang === "pt_BR" ? "Carregar mais" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}

export default App;
