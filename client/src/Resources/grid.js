import React from "react";
import "../App.css";
import Post from "./post";
import Masonry from "react-masonry-css";

const breakpointColumns = {
  default: 4,
  1200: 3,
  960: 2,
  700: 1,
};

const Grid = ({ posts }) => (
  <Masonry
    breakpointCols={breakpointColumns}
    className="masonry-grid"
    columnClassName="masonry-column"
  >
    {posts.map((post) => <Post data={post} />)}
  </Masonry>
);

export default Grid;
