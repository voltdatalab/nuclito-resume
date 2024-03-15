import React, { useEffect, useState } from "react";
import axios from "axios";
import "./App.css";
import Spinner from "./Resources/spinner"; // Make sure this path is correct
import Grid from "./Resources/grid";
import SlideShow from "./Resources/slideshow";
import { Helmet } from "react-helmet";

function App() {
  const [jsonData, setJsonData] = useState([]);
  const [loading, setLoading] = useState(true); // Add a loading state
  const amountPerPage = 12;
  const mobileMaxWidth = 700;
  const [isMobile, setIsMobile] = useState(window.innerWidth < mobileMaxWidth);

  useEffect(() => {
    setLoading(true); // Set loading to true when the component mounts and the fetch starts
    axios.get(process.env.REACT_APP_API_URL + "/post/" + amountPerPage)
      .then((response) => {
        setJsonData(response.data); // Update state with the HTML content
        setLoading(false); // Set loading to false once data is received
      })
      .catch((error) => {
        console.error("There was an error!", error);
        setLoading(false); // Also set loading to false if there's an error
      });

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
          </div>
        )}
    </div>
  );
}

export default App;
