import React from "react";
import "../App.css";
import Post from "./post";
import Masonry from "react-masonry-css";

const breakpointColumns = {
  default: 3,
  960: 2,
  700: 1,
};

const Grid = ({ posts, lang }) => (
  <Masonry
    breakpointCols={breakpointColumns}
    className="masonry-grid"
    columnClassName="masonry-column"
  >
    {posts.map((post) => <Post data={post} lang={lang} />)}
  </Masonry>
);

export default Grid;
